# -*- coding: utf-8 -*-
#Created on Tue May 28 10:27:15 2013

"""
Interpolation routines.

.. rubric:: References

.. [#IDW] http://en.wikipedia.org/wiki/Inverse_distance_weighting

.. [#BL] Lüthi, Beat. Some Aspects of Strain, Vorticity and Material Element \
   Dynamics as Measured with 3D Particle Tracking Velocimetry in a \
   Turbulent Flow. PhD Thesis, ETH-Zürich (2002).

.. [#RBF] http://en.wikipedia.org/wiki/Radial_basis_function

.. rubric:: Documentation
"""

import numpy as np, warnings
from ConfigParser import SafeConfigParser

def select_neighbs(tracer_pos, interp_points, radius=None, num_neighbs=None,
    companionship=None):
    """
    For each of m interpolation points, find its distance to all tracers. Use
    result to decide which tracers are the neighbours of each interpolation
    point, based on either a fixed radius or the closest num_neighbs.
    
    Arguments:
    tracer_pos - (n,3) array, the x,y,z coordinates of one tracer per row, [m]
    interp_points - (m,3) array, coordinates of points where interpolation will
        be done.
    radius - of the search area for neighbours, [m]. If None, select closest
        num_neighbs.
    num_neighbs - number of closest neighbours to interpolate from. If None.
        uses all neighbours in a given radius. ``radius`` has precedence.
    companionship - an optional array denoting for each interpolation point the
        index of a tracer that should be excluded from it ("companion tracer"),
        useful esp. for interpolating tracers unto themselves and for analysing
        a simulated particle that started from a true tracer.
    
    Returns:
    dists - (m,n) array, the distance from each interpolation point to each
        tracer.
    use_parts - (m,n) boolean array, True where tracer :math:`j=1...n` is a 
        neighbour of interpolation point :math:`i=1...m`.
    """
    dists =  np.linalg.norm(tracer_pos[None,:,:] - interp_points[:,None,:],
        axis=2)
    
    dists[dists <= 0] = np.inf # Only for selection phase,later changed back.
    if companionship is not None:
        cif = companionship >= 0. # companion in frame
        dists[np.nonzero(cif)[0], companionship[cif]] = np.inf
    
    if radius is None:
        if num_neighbs is None:
            raise ValueError("Either radius or num_neighbs must be given.")
        
        dist_sort = np.argsort(dists, axis=1)
        use_parts = np.zeros(dists.shape, dtype=np.bool)
        
        eff_num_neighbs = min(num_neighbs, tracer_pos.shape[0])
        use_parts[
            np.repeat(np.arange(interp_points.shape[0]), eff_num_neighbs),
            dist_sort[:,:num_neighbs].flatten()] = True
    
    else:
        use_parts = dists < radius
    
    dists[np.isinf(dists)] = 0.
    return dists, use_parts

def corrfun_interp(dists, use_parts, data, corrs_hist, corrs_bins):
    """
    For each of n particle, generate the velocity interpolated to its 
    position from all neighbours as selected by caller. The weighting of 
    neighbours is by the correlation function, e.g. if the distance at 
    neighbor i is :math:`r_i`, then it adds :math:`\\rho(r_i)*v_i` to the 
    interpolated velocity. This is done for each component separately.
    
    Arguemnts:
    dists - (m,n) array, the distance of interpolation_point :math:`i=1...m`
        from tracer :math:`j=1...n`, for (row,col) (i,j) [m] 
    use_parts - (m,n) boolean array, whether tracer j is a neighbour of 
        particle i, same indexing as ``dists``.
    data - (n,d) array, the d components of the data that is interpolated from,
        for each of n tracers.
    corrs_hist - the correlation function histogram, an array of b bins.
    corrs_bins - same size array, the bin start point for each bin.
        
    Returns:
    vel_avg - an (m,3) array with the interpolated velocity at each 
        interpolation point, [units of ``data``].
    """
    weights = np.zeros(dists.shape + (data.shape[-1],))
    weights[use_parts] = corrs_hist[
        np.digitize(dists[use_parts].flatten(), corrs_bins) - 1]
    
    vel_avg = (weights * data[None,...]).sum(axis=1) / \
        weights.sum(axis=1)

    return vel_avg

def rbf_interp(tracer_dists, dists, use_parts, data, epsilon=1e-2):
    """
    Radial-basis interpolation [3] for each particle, from all neighbours 
    selected by caller. The difference from inv_dist_interp is that the 
    weights are independent of interpolation point, among other differences.
    
    Arguments:
    tracer_dists - (n,n) array, the distance of tracer :math:`i=1...n` from 
        tracer :math:`j=1...n`, for (row,col) (i,j) [m]
    dists - (m,n) array, the distance from interpolation point 
        :math:`i=1...m` to tracer j. [m]
    use_parts - (m,n) boolean array, True where tracer :math:`j=1...n` is a 
        neighbour of interpolation point :math:`i=1...m`.
    data - (n,d) array, the d components of the data for each of n tracers.
    
    Returns:
    vel_interp - an (m,3) array with the interpolated velocity at the position
        of each particle, [m/s].
    """
    kernel = np.exp(-tracer_dists**2 * epsilon)
    
    # Determine the set of coefficients for each particle:
    coeffs = np.zeros(dists.shape + (data.shape[-1],))
    for pix in xrange(dists.shape[0]):
        neighbs = np.nonzero(use_parts[pix])[0]
        K = kernel[np.ix_(neighbs, neighbs)]
        
        coeffs[pix, neighbs] = np.linalg.solve(K, data[neighbs])
    
    rbf = np.exp(-dists**2 * epsilon)
    vel_interp = np.sum(rbf[...,None] * coeffs, axis=1)
    return vel_interp

def interpolant(method, num_neighbs=None, radius=None, param=None):
    """
    Factory function. Returns an object of the interpolant class that matches 
    the given method. All classes are subclassed from GeneralInterpolant.
    
    Arguments:
    method - interpolation method. Either 'inv' for inverse-distance 
        weighting, 'rbf' for gaussian-kernel Radial Basis Function
        method, or 'corrfun' for using a correlation function.
    radius - of the search area for neighbours, [m]. If None, select 
        closest ``neighbs``.
    neighbs - number of closest neighbours to interpolate from. If None.
        uses 4 neighbours for 'inv' method, and 7 for 'rbf', unless 
        ``radius`` is not None, then ``neighbs`` is ignored.
    param - the parameter adjusting the interpolation method. For IDW it is
        the inverse power (default 1), for rbf it is epsilon (default 1e5).
    """
    if method == 'inv':
        return InverseDistanceWeighter(num_neighbs, radius, param)
    else:
        return GeneralInterpolant(method, num_neighbs, radius, param)

Interpolant = interpolant # B.C.

class GeneralInterpolant(object):
    """
    Holds all parameters necessary for performing an interpolation. Use is as
    a callable object after initialization, see :meth:`__call__`.
    """
    def __init__(self, method, num_neighbs=None, radius=None, param=None):
        """
        Arguments:
        method - interpolation method. Either 'inv' for inverse-distance 
            weighting, 'rbf' for gaussian-kernel Radial Basis Function
            method, or 'corrfun' for using a correlation function.
        radius - of the search area for neighbours, [m]. If None, select 
            closest ``neighbs``.
        neighbs - number of closest neighbours to interpolate from. If None.
            uses 4 neighbours for 'inv' method, and 7 for 'rbf', unless 
            ``radius`` is not None, then ``neighbs`` is ignored.
        param - the parameter adjusting the interpolation method. For IDW it is
            the inverse power (default 1), for rbf it is epsilon (default 1e5).
        """        
        if method == 'rbf':
            if num_neighbs is None:
                num_neighbs = 7
            if param is None:
                param = 1e5
        
        elif method == 'corrfun':
            if num_neighbs is None:
                num_neighbs = 4
            if param is None: 
                raise ValueError("'corrfun' method requires param to be "\
                    "an NPZ file name containing the corrs and bins arrays.")
            c = np.load(param)
            self._corrs = c['corrs']
            self._bins = c['bins']
        
        else:
            raise NotImplementedError("Interpolation method %s not supported" \
                % method)
            
        self._method = method
        self._neighbs = num_neighbs
        self._radius = radius
        self._par = param
    
    def num_neighbs(self):
        return self._neighbs
    
    def radius(self):
        return self._radius
    
    def set_scene(self, tracer_pos, interp_points, data, companionship=None):
        """
        Records scene data for future interpolation using the same scene.
        
        Arguments:
        tracer_pos - (n,3) array, the x,y,z coordinates of one tracer per row, 
            in [m]
        interp_points - (m,3) array, coordinates of points where interpolation 
            will be done.
        data - (n,d) array, the for the d-dimensional data for tracer n. For 
            example, in velocity interpolation this would be (n,3), each tracer
            having 3 components of velocity.
        companionship - an optional array denoting for each interpolation point
            the index of a tracer that should be excluded from it ("companion 
            tracer"), useful esp. for analysing a simulated particle that 
            started from a true tracer.
        """
        self.__tracers = tracer_pos
        self.__interp_pts = interp_points
        self.__data = data
        self.__comp = companionship
        
        # empty the neighbours cache:
        self.__rel_pos = None
        self.__dists = None
        self.__active_neighbs = None
    
    def trim_points(self, which):
        """
        Remove interpolation points from the scene.
        
        Arguments:
        which - a boolean array, length is number of current particle list
            (as given in set_scene), True to trim a point, False to keep.
        """
        keep = ~which
        self.__interp_pts = self.__interp_pts[keep]
        if self.__dists is not None:
            self.__dists = self.__dists[keep]
            self.__active_neighbs = self.__active_neighbs[keep]
    
    def _forego_laziness(self):
        """
        Populate the neighbours cache.
        """
        self.__rel_pos = self.__tracers[None,:,:] - self.__interp_pts[:,None,:]
        self.__dists, self.__active_neighbs = select_neighbs(
            self.__tracers, self.__interp_pts, self._radius, self._neighbs,
            self.__comp)
            
        if self._method == 'rbf':
            self.__tracer_dists, _ = select_neighbs(
                self.__tracers, self.__tracers, self._radius, self._neighbs,
                self.__comp)
                
    def which_neighbours(self):
        """
        Finds the neighbours that would be selected for use at each 
        interpolation point, given the current scene as set by set_scene().
        
        Returns:
        (m,n) boolean array, True where tracer :math:`j=1...n` is a neighbour
        of interpolation point :math:`i=1...m` under the reigning selection 
        criteria.
        """
        if self.__active_neighbs is None:
            self._forego_laziness()
                
        return self.__active_neighbs
    
    def current_relative_positions(self):
        """
        Returns an (m,n,3) array, the distance between interpolation point m
        and tracer n an each axis.
        """
        return self.__rel_pos
    
    def current_dists(self):
        if self.__active_neighbs is None:
            self._forego_laziness()
                
        return self.__dists
    
    def current_active_neighbs(self):
        if self.__active_neighbs is None:
            self._forego_laziness()
                
        return self.__active_neighbs
    
    def current_data(self):
        if self.__active_neighbs is None:
            self._forego_laziness()
                
        return self.__data
    
    def interpolate(self, subset=None):
        """
        Performs an interpolation over the recorded scene.
        
        Arguments:
        subset - a neighbours selection array, such as returned from 
            :meth:`which_neighbours`, to replace the recorded selection. Default
            value (None) uses the recorded selection. The recorded selection
            is not changed, so ``subset`` is forgotten after the call.
        
        Returns:
        an (m,3) array with the interpolated value at the position of each 
        of m particles.
        """
        # If for some reason tracking failed for a whole frame, 
        # interpolation is impossible at that frame. This checks for frame 
        # tracking failure.
        if len(self.__tracers) == 0:
            # Temporary measure until I can safely discard frames.
            warnings.warn("No tracers in frame, interpolation returned zeros.")
            ret_shape = self.__data.shape[-1] if self.__data.ndim > 1 else 1
            return np.zeros((self.__interp_pts.shape[0], ret_shape))

        # Check that the cache is populated:
        if self.__active_neighbs is None:
            self._forego_laziness()
        
        act_neighbs = self.__active_neighbs if subset is None else subset
            
        return self._meth_interp(act_neighbs)
    
    def _meth_interp(self, act_neighbs):
        """
        Implement the actual interpolation. Subclass this, not 
        :meth:`interpolate`.
        
        Arguments:
        act_neighbs - a neighbours selection array, such as returned from 
            :meth:`which_neighbours`, to replace the recorded selection. Default
            value (None) uses the recorded selection. The recorded selection
            is not changed, so ``subset`` is forgotten after the call.
        """
        if self._method == 'rbf':
            return rbf_interp(self.__tracer_dists, self.__dists, act_neighbs,
                self.__data, self._par)
        
        if self._method == 'corrfun':
            return corrfun_interp(self.__dists, act_neighbs, self.__data, 
                self._corrs, self._bins)
        
        # This isn't supposed to ever happen. The constructor should fail.
        raise NotImplementedError("Interpolation method %s not supported" \
            % self._method)
    
    def __call__(self, tracer_pos, interp_points, data, companionship=None):
        """
        Sets up the necessary parameters, and performs the interpolation.
        Does not change the scene set by set_scene if any, so may be used
        for any off-scene interpolation.
        
        Arguments:
        tracer_pos - (n,3) array, the x,y,z coordinates of one tracer per row, 
            in [m]
        interp_points - (m,3) array, coordinates of points where interpolation 
            will be done.
        data - (n,d) array, the for the d-dimensional data for tracer n. For 
            example, in velocity interpolation this would be (n,3), each tracer
            having 3 components of velocity.
        companionship - an optional array denoting for each interpolation point
            the index of a tracer that should be excluded from it ("companion 
            tracer"), useful esp. for analysing a simulated particle that 
            started from a true tracer.
        
        Returns:
        vel_interp - an (m,3) array with the interpolated value at the position
            of each particle, [m/s].
        """
        # If for some reason tracking failed for a whole frame, interpolation 
        # is impossible at that frame. This checks for frame tracking failure.
        if len(tracer_pos) == 0:
            # Temporary measure until I can safely discard frames.
            warnings.warn("No tracers im frame, interpolation returned zeros.")
            ret_shape = data.shape[-1] if data.ndim > 1 else 1
            return np.zeros((interp_points.shape[0], ret_shape))
            
        dists, use_parts = select_neighbs(tracer_pos, interp_points, 
            self._radius, self._neighbs, companionship)
        
        if self._method == 'rbf':
            tracer_dists = select_neighbs(tracer_pos, tracer_pos, 
                self._radius, self._neighbs, companionship)[0]
            return rbf_interp(tracer_dists, dists, use_parts, data, self._par)
        
        elif self._method == 'corrfun':
            return corrfun_interp(dists, use_parts, data,
                self._corrs, self._bins)
        
        else:
            # This isn't supposed to ever happen. The constructor should fail.
            raise NotImplementedError("Interpolation method %s not supported" \
                % self._method)
            
    def eulerian_jacobian(self, local_interp=None, eps=100e-6):
        """
        A general way to calculate the velocity derivatives. It could be
        enhanced in the future by specific analytical derivatives of the
        different interpolation methods. The Jacobian is calculated for the
        current scene, as recorded with ``set_scene()``
        
        Arguments:
        local_interp - results of interpolation already performed at the 
            position where derivatives are wanted. If not given, an 
            interpolation of recorded scene data is automatically performed.
        eps - the dx in each direction.
        
        Returns: (m,3,3) array, for m interpolation points, [i,j] = du_i/dx_j
        """
        if local_interp is None:
            local_interp = self.interpolate()

        ret = np.empty((self.__interp_pts.shape[0], 3, 3))
        ret[:,:,0] = self(self.__tracers,
            self.__interp_pts + np.r_[eps,0,0], self.__data) 
        ret[:,:,1] = self(self.__tracers, 
            self.__interp_pts + np.r_[0,eps,0], self.__data) 
        ret[:,:,2] = self(self.__tracers, 
            self.__interp_pts + np.r_[0,0,eps], self.__data)
        ret = (ret - local_interp[:,:,None]) / eps
        return ret
        
    def neighb_dists(self, tracer_pos, interp_points, companionship=None):
        """
        The distance from each interpolation point to each data point of those
        used for interpolation. Assumes, for now, a constant number of
        neighbours.
        
        Arguments:
        tracer_pos - (n,3) array, the x,y,z coordinates of one tracer per row, 
            in [m]
        interp_points - (m,3) array, coordinates of points where interpolation 
            will be done.
        companionship - an optional array denoting for each interpolation point
            the index of a tracer that should be excluded from it ("companion 
            tracer"), useful esp. for analysing a simulated particle that 
            started from a true tracer.
        
        Returns:
        ndists - an (m,c) array, for c closest neighbours as defined during
            object construction.
        """
        dists, use_parts = select_neighbs(tracer_pos, interp_points, 
            None, self._neighbs, companionship)
        
        nearest_tracers_count = min(tracer_pos.shape[0], self._neighbs)
        ndists = np.zeros((interp_points.shape[0], nearest_tracers_count))
        
        for pt in xrange(interp_points.shape[0]):
            # allow assignment of less than the desired number of neighbours.
            ndists[pt] = dists[pt, use_parts[pt]]
        
        return ndists
    
    def save_config(self, cfg):
        """
        Adds the keys necessary for recreating this interpolant into a 
        configuration object. It is the caller's responsibility to do a 
        writeback to file.
        
        Arguments:
        cfg - a ConfigParser object.
        """
        if not cfg.has_section("Interpolant"):
            cfg.add_section("Interpolant")
        cfg.set('Interpolant', 'radius', str(self.radius()))
        cfg.set('Interpolant', 'num_neighbs', str(self.num_neighbs()))
        cfg.set('Interpolant', 'param', str(self._par))
        cfg.set('Interpolant', 'method', self._method)

class InverseDistanceWeighter(GeneralInterpolant):
    """
    Holds all parameters necessary for performing an inverse-distance 
    interpolation [#IDW]_. Use is either as a callable object after 
    initialization, see :meth:`__call__`, or by setting a scene for repeated 
    interpolation, see :meth:`set_scene` and :meth:`interpolate`
    """
    def __init__(self, num_neighbs=None, radius=None, param=None):
        """
        Arguments:
        num_neighbs - number of closest neighbours to interpolate from. If None
            uses 4 neighbours, unless ``radius`` is not None, then ``neighbs``
            is ignored.
        radius - of the search area for neighbours, [m]. If None, select 
            closest ``neighbs``.
        param - the inverse power of distance to use (default 1).
        """
        if num_neighbs is None:
            num_neighbs = 4
        if param is None: 
            param = 1
        
        self._neighbs = num_neighbs
        self._radius = radius
        self._par = param
        self._method = 'inv'
    
    def weights(self, dists, use_parts):
        """
        Calculate the respective weight of each tracer j=1..n in the 
        interpolation point i=1..m. The actual weight is normalized to the sum
        of weights in the interpolation, not here.
    
        Arguments:
        dists - (m,n) array, the distance of interpolation_point i=1...m from 
            tracer j=1...n, for (row,col) (i,j) [m] 
        use_parts - (m,n) boolean array, whether tracer j is a neighbour of 
            particle i, same indexing as ``dists``.
        
        Returns:
        weights - an (m,n) array.
        """
        weights = np.zeros_like(dists)
        weights[use_parts] = dists[use_parts]**-self._par
        return weights
    
    def _apply_weights(self, weights, data):
        """
        Do the actual interpolation after weights have been determined.
        
        Arguments:
        weights - an (m,n) array, the respective non-normalized weight of each 
            tracer j=1..n in the interpolation point i=1..m.
        data - an (n,d) array, for n data points to interpolate from.
        """
        return (weights[...,None] * data[None,...]).sum(axis=1) / \
            weights.sum(axis=1)[:,None]
    
    def __call__(self, tracer_pos, interp_points, data, companionship=None):
        """
        Sets up the necessary parameters, and performs the interpolation.
        Does not change the scene set by set_scene if any, so may be used
        for any off-scene interpolation.
        
        Arguments:
        tracer_pos - (n,3) array, the x,y,z coordinates of one tracer per row, 
            in [m]
        interp_points - (m,3) array, coordinates of points where interpolation 
            will be done.
        data - (n,d) array, the for the d-dimensional data for tracer n. For 
            example, in velocity interpolation this would be (n,3), each tracer
            having 3 components of velocity.
        companionship - an optional array denoting for each interpolation point
            the index of a tracer that should be excluded from it ("companion 
            tracer"), useful esp. for analysing a simulated particle that 
            started from a true tracer.
        
        Returns:
        vel_interp - an (m,3) array with the interpolated value at the position
            of each particle, [m/s].
        """
        # If for some reason tracking failed for a whole frame, interpolation 
        # is impossible at that frame. This checks for frame tracking failure.
        if len(tracer_pos) == 0:
            # Temporary measure until I can safely discard frames.
            warnings.warn("No tracers im frame, interpolation returned zeros.")
            ret_shape = data.shape[-1] if data.ndim > 1 else 1
            return np.zeros((interp_points.shape[0], ret_shape))
            
        dists, use_parts = select_neighbs(tracer_pos, interp_points, 
            self._radius, self._neighbs, companionship)
        
        self.__weights = self.weights(dists, use_parts)
        return self._apply_weights(self.__weights, data)
        
    def _meth_interp(self, act_neighbs):
        """
        Implement the actual interpolation. Subclass this, not 
        :meth:`interpolate`.
        
        Arguments:
        act_neighbs - a neighbours selection array, such as returned from 
            :meth:`which_neighbours`, to replace the recorded selection. Default
            value (None) uses the recorded selection. The recorded selection
            is not changed, so ``subset`` is forgotten after the call.
        """
        self.__weights = self.weights(self.current_dists(), act_neighbs)
        return self._apply_weights(self.__weights, self.current_data())
    
    def eulerian_jacobian(self, local_interp=None, eps=None):
        """
        Velocity derivatives. The Jacobian is calculated for the
        current scene, as recorded with ``set_scene()``
        
        Arguments:
        local_interp - results of interpolation already performed at the 
            position where derivatives are wanted. If not given, an 
            interpolation of recorded scene data is automatically performed.
        eps - unused, here for compatibility with base class.
        
        Returns: 
        (m,d,3) array, for m interpolation points and d interpolation 
        dimentions. For each point, [i,j] = du_i/dx_j
        """
        if local_interp is None:
            local_interp = self.interpolate()
        
        dists = self.current_dists()
        use_parts = self.current_active_neighbs()
        rel_pos = self.current_relative_positions()
        data = self.current_data().copy()
        
        der_inv_dists = np.zeros_like(dists)
        der_inv_dists[use_parts] = dists[use_parts]**-(self._par + 2)
        
        vel_diffs = (data[None,:,:] - local_interp[:,None,:]) # m x n x d
        jac = self._par/self.__weights.sum(axis=1) * \
            np.sum(der_inv_dists[...,None,None]*rel_pos[:,:,None,:]*\
                   vel_diffs[...,None], axis=1)
        
        return jac
    
def read_interpolant(conf_fname):
    """
    Builds an Interpolant object based on values in an INI-formatted file.
    
    Arguments:
    conf_fname - path to configuration file.
    
    Returns:
    an Interpolant object constructed from values in the configuration file.
    """
    parser = SafeConfigParser()
    parser.read(conf_fname)
    
    # Optional arguments:
    kwds = {}
    if parser.has_option('Interpolant', 'num_neighbs'):
        kwds['num_neighbs'] = parser.getint('Interpolant', 'num_neighbs')
    if parser.has_option('Interpolant', 'radius'):
        kwds['radius'] = parser.getfloat('Interpolant', 'radius')
    if parser.has_option('Interpolant', 'param'):
        kwds['param'] = parser.getfloat('Interpolant', 'param')
    
    return interpolant(parser.get('Interpolant', 'method'), **kwds)
