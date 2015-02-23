'''

SED Machine Extraction class
(c) 2014 Nick Konidaris


This class is an abstract wrapper around the extraction

'''
from numpy.polynomial.chebyshev import chebfit, chebval
import numpy as np


class Extraction():
    '''SED machine spectral extraction class.

    Generally there are several thousand such Extractions that are held for
    a single 2k x 2k frame. 

    Args:
        seg_id (int): Number from 1 to the maximum segment number. The segment
            number is generated by sextractor.
        ok (bool): Flag indicating the success of wavelength solutions
        xrange([int,int]): From sextractor, the beginning and end of the segment.
            Usually ~ 250 pixels long.
        yrange([int,int]): From sextractor, the top and bottom of the segment.
            Usually less than ~4 pixels.
        poly ([float]): Coefficients to the polynomial function tracing the
            ridge of each spectrum. Is converted to a polynomial function via
            np.poly1d. The function parameter is a pixel integer starting
            from xrange[0]
        trace_sigma (float): The width of the trace that would be used for "optimal"
           type extractions. The value of trace_sigma represents one standard 
           deviation. Unit is pixel.
        profile_sd (float): Profile standard deviation of extraction along ridgeline
        spec ([float]): The extracted 1d spectrum.
        specw ([flaot]): The extracted 1d spectrum extracted using the profile trace.
        hg_lines ({wavelength: pixel}): An association of mercury lamp wavelength
            and pixel position. These values come from sextractor
        hgcoef ([float]): Chebyshev polynomial coefficients to the best-fit
            mercury lamp spectrum. Used as an intermediate step. Do not use
            in general.
        mdn_coeff([float]): Chebyshev polynomial coefficients to the best-fit
            mercury and xe lamp spectrum. lamcoeff should be used as the 
            wavelength solution. Defaults to None.
        lamcoeff([float]): Chebyshev polynomial coefficients to the best-fit
            mercury and xe lamp spectrum. lamcoeff should be used as the 
            wavelength solution. Defaults to None.
        lamrms(float): The RMS residual for the best wavelength solution.
        X_as(float): The relative position of the spaxel in arcsec
        Y_as(float): The relative position of the spaxel in arcsec
        Q_ix(int): Q coordinate of the pixel in axial units
        R_iq(int): R coordinate of the pixel in axial units

    Examples:
        You should use the values as follows:

        extractions = np.load(...)

        extraction = extractions[500] # 500 is arbitrary for this example
        pixel = 30
        X = extraction.xrange[0] + pixel
        wavelength = chebval(pixel, extraction.lamcoeff)

        print "The spectrum starting at %i and pixel %i is %f" % \
            (extraction.xrange[0], pixel, wavelength)

    '''

    seg_id = None 
    ok = None
    xrange = None
    yrange = None
    poly = None
    spec = None
    specw = None
    hg_lines = None
    hgcoef = None
    mdn_coeff = None
    trace_sigma = None

    lamcoeff = None
    lamrms = None
    exptime = None

    Q_ix = None
    R_ix = None
    X_as = None
    Y_as = None

    def get_flambda(self, the_spec='specw'):
        ''' Returns [wavelength, Flambda] spectrum.

        wavelength in nm
        Flambda in Electron/nm/10 min
        
        Both are around 250 pixels long
        
        Args:
            the_spec: Either 'spec' for the top-hat extracted
                spectrum or 'specw' for the weighted 
                (so called optimal) extraction.
        '''

        dlam = self.get_dlambda()
        min = 60.0
        
        lam = self.get_lambda_nm()

        if the_spec == 'spec':
            ss = self.spec
        else:
            ss = self.specw

        el_p10m = ss*(min*10)/self.exptime
        return [lam, el_p10m/dlam]


    def get_lambda_nm(self):
        '''Returns lambda spectrum in nm'''
        xs = np.arange(*self.xrange)
        
        if self.mdn_coeff is not None:
            lam = chebval(xs, self.mdn_coeff)
        else:
            lam = chebval(xs, self.lamcoeff)

        return lam

    def get_dlambda(self):
        '''Returns dlambda spectrum '''

        # Note the +1 below to handle the eating of an element
        # by diff
        xs = np.arange(self.xrange[0], self.xrange[1]+1)

        if self.mdn_coeff is not None:
            lam = chebval(xs, self.mdn_coeff)
        else:
            lam = chebval(xs, self.lamcoeff)
        dlam = np.abs(np.diff(lam))
        

        return dlam

        

        



    def __init__(self, seg_id=None, ok=None, xrange=None, 
        yrange=None, poly=None, spec=None, specw=None,
        exptime=exptime, trace_sigma = None, hg_lines = None,
        X_as=None, Y_as=None, Q_ix=None, R_ix=None):
        

        self.seg_id = seg_id
        self.ok = ok
        self.xrange = xrange
        self.yrange = yrange
        self.poly = poly
        self.spec = spec
        self.specw = specw
        self.hg_lines = hg_lines
        self.exptime = exptime
        self.trace_sigma = trace_sigma
        self.X_as = X_as
        self.Y_as = Y_as
        self.Q_ix = Q_ix
        self.R_ix = R_ix
