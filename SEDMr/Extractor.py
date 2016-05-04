
import argparse
import os
import numpy as np
import pylab as pl
import pyfits as pf
import scipy.signal as SG
import sets
import itertools
import warnings

from astropy.coordinates import Angle
from astropy.time import Time
from numpy.polynomial.chebyshev import chebfit, chebval
from scipy.interpolate import interp1d
from scipy.ndimage import filters
import SEDMr.Wavelength as Wavelength
import SEDMr.Spectra as SS
import SEDMr.GUI as GUI
import NPK.Util
import NPK.Standards as Stds
import NPK.Atmosphere as Atm

# Nadia imports
from scipy.interpolate import griddata
import scipy.optimize as opt


def reject_outliers(data, m=2.):
    d = np.abs(data - np.median(data))
    mdev = np.median(d)
    d[d != d] = 100000.
    s = d/mdev if mdev else 0.
    return data[s<m]


def atm_dispersion_positions(PRLLTC, pos, leff, airmass):
    """ Return list of (X,Y) positions indicating trace of atmospheric dispersion

    Args:
        PRLLTC: parralactic angle in Angle class
        pos: (x,y) position of source in arcsec at wavelength leff
        leff: Effective wavelength, micron
        airmass: Atmospheric airmass. Note, if airmass=1 there's no dispersion

    Returns:
        List of positions of the source in arcsec: [ (x0,y0) ... (xn,yn) ]

        Note: if airmass=1, then the list is equivalent of [ pos ]

    """
    print "LamEff %.1f nm, Airmass %.3f" % (leff, airmass)

    blue_ad = NPK.Util.atm_disper(0.38, leff, airmass)
    red_ad  = NPK.Util.atm_disper(leff, 0.95, airmass)
    print 'Blue AD is %1.1f", Red AD is %1.1f" PRLLTC %3.1f' % (blue_ad, red_ad,
        PRLLTC.degree)

    dx = -np.sin(PRLLTC.radian)
    dy =  np.cos(PRLLTC.radian)

    DELTA = 0.1
    bpos = np.array(pos) - np.array([dx, dy]) * blue_ad * DELTA

    positions = []
    nstep = np.int(np.round((blue_ad - red_ad)/DELTA))
    if nstep == 0: nstep=1
    for delta in xrange(nstep):
        t = [bpos[0] + delta * dx * DELTA, bpos[1] + delta * dy * DELTA]
        positions.append(t)

    DX = positions[0][0] - positions[-1][0]
    DY = positions[0][1] - positions[-1][1]

    print "DX %2.1f, DY %2.1f, D %2.1f" % (DX, DY, np.sqrt(DX*DX + DY*DY))
    return positions


def Gaussian_2D(xdata_tuple, amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
    '''
    Produces a 2D gaussian centered in xo, yo with the parameters specified.
    xdata_tuple: coordinates of the points where the 2D Gaussian is computed.

    '''
    (x, y) = xdata_tuple
    xo = float(xo)
    yo = float(yo)
    a = (np.cos(theta)**2)/(2*sigma_x**2) + (np.sin(theta)**2)/(2*sigma_y**2)
    b = -(np.sin(2*theta))/(4*sigma_x**2) + (np.sin(2*theta))/(4*sigma_y**2)
    c = (np.sin(theta)**2)/(2*sigma_x**2) + (np.cos(theta)**2)/(2*sigma_y**2)
    g = offset + amplitude*np.exp( - (a*((x-xo)**2) + 2*b*(x-xo)*(y-yo) + c*((y-yo)**2)))
    return g.ravel()


def identify_spectra_Gauss_fit(spectra, outname=None, PRLLTC=None,
                               lmin=400, lmax=900, airmass=1.0):
    """ 
     Returns index of spectra picked by Guassian fit.
    
    NOTE: Index is counted against the array, not seg_id
    """
    pl.ioff()
    
    KT = SS.Spectra(spectra)   
    
    # Get X,Y positions (arcsec) and summed values between lmin and lmax
    Xs, Ys, Vs = KT.to_xyv(lmin=lmin, lmax=lmax)
    
    xi = np.linspace(np.nanmin(Xs),np.nanmax(Xs),100)
    yi = np.linspace(np.nanmin(Ys),np.nanmax(Ys),200)
    
    X, Y = np.mgrid[np.nanmin(Xs):np.nanmax(Xs):100j, 
                    np.nanmin(Ys):np.nanmax(Ys):200j]

    points = zip(Xs, Ys)
    values = Vs
    
    grid_Vs = griddata(points, values, (X, Y), method='linear')
    grid_Vs[np.isnan(grid_Vs)] = np.nanmean(grid_Vs)
    print("grid_Vs min, max, mean: %f, %f, %f" % 
            (np.nanmin(grid_Vs), np.nanmax(grid_Vs), np.nanmean(grid_Vs)))
    
    # Initialize the first guess for the Gaussian
    xo = xi[np.argmax(np.nansum(grid_Vs, axis=1))]
    yo = yi[np.argmax(np.nansum(grid_Vs, axis=0))]
    sigma_x = 1.
    sigma_y = 1.3
    amplitude = np.nanmax(Vs)
    print("initial guess: z,x,y,a,b: %f, %f, %f, %f, %f" %
            (amplitude, xo, yo, sigma_x, sigma_y))
    
    # create data
    initial_guess = (amplitude, xo, yo, sigma_x, sigma_y, 0, 
                        np.nanmean(grid_Vs))

    popt, pcov = opt.curve_fit(Gaussian_2D, (X, Y),
                                grid_Vs.flatten(), p0=initial_guess)
    xc = popt[1]
    if xc < -30. or xc > 30.:
        print "Warning: X out of bounds, using initial guess: %f" % xc
        xc = xo
    yc = popt[2]
    if yc < -30. or yc > 30.:
        print "Warning: Y out of bounds, using initial guess: %f" % yc
        yc = yo
    pos  = (xc, yc)
    
    # get 3-sigma extent
    a = popt[3]*3.
    b = popt[4]*3.
    theta = popt[5]
    
    # report position and shape
    print "PSF FIT on IFU:  X,Y,a,b,theta = ",xc,yc,a,b,theta
    
    leff = (lmax+lmin)/2.0
    
    if PRLLTC is not None:
        positions = atm_dispersion_positions(PRLLTC, pos, leff, airmass)
    else:
        positions = [pos]
    
    all_kix = []
    for the_pos in positions:
        all_kix.append( list(find_positions_ellipse( KT.KT.data,  xc, yc, a, b,
                                                                    -theta)))

    all_kix = list(itertools.chain(*all_kix))
    kix = list(sets.Set(all_kix))
    print "found this many spaxels: %d" % len(kix)
    
    return KT.good_positions[kix], pos, positions, a


def find_positions_ellipse(xy, h, k, a, b, A):
    """
    xy: Vector with pairs [[x0, y0], [x1, y1]] of coordinates.
    a: semi-major axis of ellipse in X axis.
    b: semi-minor axis of ellipse in Y axis.
    h: central point ellipse in X axis.
    k: central point ellipse in Y axis.
    A: angle of rotation of ellipse in radians (clockwise).
    """
    positions = np.arange(len(xy))
    x = xy[:,0]
    y = xy[:,1]
    dist = ((x-h)*np.cos(A)+(y-k)*np.sin(A))**2/(a**2) + \
        ((x-h)*np.sin(A)-(y-k)*np.cos(A))**2/(b**2)
    
    return positions[dist<1]


def identify_spectra_gui(spectra, outname=None, radius=2, 
                         lmin=650, lmax=700, PRLLTC=None, 
                         object=object, airmass=1.0):
    """ Returns index of spectra picked in GUI.

    NOTE: Index is counted against the array, not seg_id
    """

    print "\nStarting with a %s arcsec radius" % radius
    KT = SS.Spectra(spectra)
    g = GUI.PositionPicker(KT, bgd_sub=True, radius_as=radius, 
                            lmin=lmin, lmax=lmax, objname=object)
    pos  = g.picked
    radius = g.radius_as
    print "Final radius (arcsec) = %4.1f" % radius

    leff = (lmax+lmin)/2.0
    if PRLLTC is not None:
        positions = atm_dispersion_positions(PRLLTC, pos, leff, airmass)
    else:
        positions = [pos]

    all_kix = []
    for the_pos in positions:
        all_kix.append(KT.KT.query_ball_point( the_pos, radius ))

    all_kix = list(itertools.chain(*all_kix))
    kix = list(sets.Set(all_kix))

    return KT.good_positions[kix], pos, positions, radius


def identify_sky_spectra(spectra, pos, inner=3, lmin=650, lmax=700):
    KT = SS.Spectra(spectra)

    outer = inner + 3

    skys = KT.good_positions.tolist()
    objs = KT.good_positions[KT.KT.query_ball_point(pos, r=outer)]

    for o in objs:
        if o in skys: skys.remove(o)

    newspec = [ spectra[i] for i in skys ]
    KT = SS.Spectra(newspec)

    Xs, Ys, Vs = KT.to_xyv(lmin=lmin, lmax=lmax)
    Vmdn = np.median(Vs)

    Vstd = np.nanstd(Vs)

    hi_thresh = Vmdn + 1.25 * Vstd
    lo_thresh = Vmdn - 2.0 * Vstd
    print("Median: %6.2f, STD: %6.2f, Hi Thresh: %6.2f, Lo Thresh: %6.2f" %
            (Vmdn, Vstd, hi_thresh, lo_thresh))

    KT = SS.Spectra(spectra)

    n_hi_rem = 0
    n_lo_rem = 0
    n_tot = 0

    for s in skys:
        el = spectra[s]
        l,fl = el.get_flambda()

        ok = (l > lmin) & (l <= lmax)

        if np.median(el.spec[ok]) > hi_thresh:
            skys.remove(s)
            n_hi_rem += 1

        if np.median(el.spec[ok]) < lo_thresh:
            skys.remove(s)
            n_lo_rem += 1

        n_tot += 1

    n_tot = n_tot - (n_hi_rem + n_lo_rem)
    print("Removed %d high sky spaxels and %d low sky spaxels leaving %d remaining spaxels" % (n_hi_rem, n_lo_rem, n_tot))

    return skys


def identify_bgd_spectra(spectra, pos, inner=3, outer=6):
    KT = SS.Spectra(spectra)

    outer = inner + 3

    objs = KT.good_positions[KT.KT.query_ball_point(pos, r=inner)]
    skys = KT.good_positions[KT.KT.query_ball_point(pos, r=outer)].tolist()

    for o in objs:
        if o in skys: skys.remove(o)

    return skys


def identify_spectra(spectra, outname=None, low=-np.inf, hi=np.inf, plot=False):

    raise Exception("This code is outdated")

    ms = []
    ixs = []
    segids = []

    ds9 = "physical\n"
    for ix,spectrum in enumerate(spectra):
        if spectrum.__dict__.has_key('spec') and spectrum.spec is not None \
            and spectrum.lamcoeff is not None:
            ixs.append(ix)
            segids.append(spectrum.seg_id)

            try: l,s = spectrum.get_counts(the_spec='specw')
            except:
                ms.append(0)
                continue


            ms.append(np.median(s))
            X = spectrum.X_as
            Y = spectrum.Y_as

            ds9 += 'point(%s,%s) # point=cross text={%s:%4.2f}\n' % \
                (X,Y, segids[-1],ms[-1])

    ixs = np.array(ixs)
    ms = np.array(ms)
    bgd = np.median(ms)
    sd = np.std(ms)
    segids = np.array(segids)

    ms -= bgd

    ok = (ms <= sd*low) | (ms >= sd*hi)
    pl.figure(1)
    pl.clf()
    bgd = (ms > sd*low) & (ms < sd*hi)
    pl.plot(segids[bgd], ms[bgd],'.')
    pl.plot(segids[ok], ms[ok],'x')
    pl.axhline(sd*low,color='orange')
    pl.axhline(sd*hi,color='red')
    pl.xlabel("Sextractor Segment ID number")
    pl.ylabel("Median spectral irradiance [photon/10 m/nm]")
    pl.legend(["Bgd spectra", "Selected spectra"])
    pl.grid(True)
    if outname is not None:
        pl.savefig("selected_%s.pdf" % outname)
        print "Wrote selected_%s.pdf" % outname
    if plot:
        pl.show()

    f = open(outname + ".reg", "w")
    f.write(ds9)
    f.close()

    to_image(outname)

    return ixs[ok]


def to_image(spectra, meta, outname, posA=None, posB=None, adcpos=None):
    """ Convert spectra list into image_[outname].pdf """

    Xs = []
    Ys = []
    Vs = []

    for x in spectra:
        if x.xrange is None: continue
        if x.lamcoeff is None: continue
        if x.specw is None: continue
        ix = np.arange(*x.xrange)
        ll = chebval(ix, x.lamcoeff)
        OK = (ll > 650) & (ll < 700)
        if OK.any():
            Xs.append(x.X_as)
            Ys.append(x.Y_as)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                Vs.append(np.median(x.specw[OK]))

    # Clean outliers
    Vcln = reject_outliers(np.array(Vs, dtype=np.float), m=3.)
    Vstd = np.nanstd(Vcln)
    Vmid = np.median(Vcln)
    if posB is None:
        Vmin = Vmid - Vstd
        Vmax = Vmid + 8.*Vstd
    else:
        Vmin = Vmid - 8.*Vstd
        Vmax = Vmid + 8.*Vstd
    pl.clf()
    pl.ylim(-20, 20)
    pl.xlim(-22, 20)
    pl.grid(True)
    if posA is not None:
        pl.axvline(posA[0], color='black', linewidth=.5)
        pl.axhline(posA[1], color='black', linewidth=.5)
    if posB is not None:
        pl.axvline(posB[0], color='black', linewidth=.5)
        pl.axhline(posB[1], color='black', linewidth=.5)
    pl.scatter(Xs, Ys, c=Vs, s=50, marker='H', linewidth=0,
            vmin=Vmin, vmax=Vmax)

    if adcpos is not None:
        for p in adcpos:
            pl.plot(p[0], p[1], 'rx')

    pl.xlabel("X [as] @ %6.1f nm" % meta['fiducial_wavelength'])
    pl.ylabel("Y [as]")
    pl.title(meta['outname'])
    pl.colorbar()
    pl.savefig("image_%s.pdf" % outname)
    pl.close()
    print "Wrote image_%s.pdf" % outname


def c_to_nm(coefficients, pix, offset=0):

    t = coefficients[:]
    t[0] += offset
    return chebval(pix, t)


def interp_spectra(all_spectra, six, sign=1., outname=None, plot=False,
    corrfile=None, dnm=0, onto=None):
    """Interp spectra onto common grid

    Args:
        all_spectra:
        six:
        dnm: Offset (usually for flexure) in nm
    """

    l_grid = onto
    s_grid = []
    lamcoeff = None
    #for ix,spectrum in enumerate(all_spectra):
    for ix in six:
        spectrum = all_spectra[ix]

        l,s = spectrum.get_counts(the_spec='specw')
        pix = np.arange(*spectrum.xrange)

        # This is wrong: should give preference to lamcoeff according to Nick
        #if spectrum.mdn_coeff is not None: cs = spectrum.mdn_coeff
        #else: cs = spectrum.lamcoeff

        # This is correct: preference to lamcoeff over mdn_coeff
        if spectrum.lamcoeff is not None: cs = spectrum.lamcoeff
        else: cs = spectrum.mdn_coeff

        # get wavelengths for spectrum
        l = c_to_nm(cs, pix, offset=dnm)

        # skip short spectra (on or near edge of IFU)
        if l.max() - l.min() < 300: continue

        # Positive or negative spectra
        pon = sign

        # Check if our wavelength grid is defined,
        if l_grid is None:
            # use the first set of wavelengths and store
            l_grid = l
            s_grid.append(s*pon)
            lamcoeff = spectrum.lamcoeff
        else:
            # Interpolate onto our wavelength grid and store
            fun = interp1d(l,s*pon, bounds_error=False,fill_value=0)
            s_grid.append(fun(l_grid))

    # average of all spectra selected
    # I wonder if this should be a weighted mean?
    #medspec = np.mean(s_grid, 0)
    medspec = np.nanmean(s_grid, axis=0)

    # Output figures if requested

    # Spectrum
    pl.figure(3)
    pl.clf()
    pl.step(l_grid,medspec)
    yl = pl.ylim()
    pl.xlabel('Wavelength [nm]')
    pl.ylabel(r'Spectral irradiance[photon/10 m/nm]')
    pl.grid(True)
    if outname is not None:
        pl.savefig("spec_%s" % outname)
        print "Wrote spec_%s" % outname
    if plot: pl.show()

    # Spaxel stack image
    pl.figure(2)
    pl.clf()
    s_grid = np.array(s_grid)
    pl.imshow(s_grid,vmin=yl[0], vmax=yl[1])
    pl.xlabel('Wavelength bin [pixel]')
    pl.colorbar()
    pl.grid(True)
    if outname is not None: 
        pl.savefig("allspec_%s" % outname)
        print "Wrote allspec_%s" % outname
    if plot:pl.show()

    # Package results
    doc = """Result contains:
        nm [N float]: Wavelength solution
        ph_10m_nm [N float]: Spectral irradiance of source in units of photon / 10 minute / nm
        spectra [? x K float]: List of all the spectra that participated in
            the formation of ph_10m_nm. By interpolating these objects onto
            a ph_10m_nm and taking the mean, you produce ph_10m_nm
        coefficients [3-5 element float]: Chebyshev coefficents that produce
            nm. Can be evaluated with numpy chebval().
        corrected-spec [N float]: ph_10m_nm * Atmospheric correction, if
            available
        doc: This doc string
        """
    result = [{"nm": l_grid, "ph_10m_nm": medspec, "spectra": s_grid,
        "coefficients": lamcoeff,
        "doc": doc}]

    # Calibrate output if corrfile specified (this is not usually done)
    CC = None

    # Try to load corrfile
    if corrfile is not None:
        try: CC = np.load(corrfile)[0]
        except: CC = None

    # Apply correction
    if CC is not None:
        corrfun = chebval(l_grid, CC['coeff'])
        corrfun /= np.nanmin(corrfun)
        corrfun = interp1d(CC['nm'], CC['cor'], bounds_error=False, fill_value=np.nan)
        corrfun = corrfun(l_grid)
        result[0]['corrected-spec'] = medspec * corrfun

        # Output corrected spectrum if requested
        pl.figure(4)
        pl.clf()
        pl.step(l_grid,medspec*corrfun)
        pl.ylim(yl[0], yl[1]*20)
        pl.xlabel('Wavelength [nm]')
        pl.ylabel(r'Spectral irradiance[photon/10 m/nm] x Atm correction')
        pl.grid(True)
        if outname is not None:
            pl.savefig("corr_spec_%s" % outname)
            print "Wrote corr_spec_%s" % outname
        if plot: pl.show()

    pl.figure(2)

    return result


def load_corr():
    corr = pf.open("CORR.npy")


def imarith(operand1, op, operand2, result, doAirmass=False):
    from pyraf import iraf
    iraf.images()

    pars = iraf.imarith.getParList()
    iraf.imcombine.unlearn()

    try: os.remove(result)
    except: pass

    print "%s %s %s -> %s" % (operand1, op, operand2, result)
    iraf.imarith(operand1=operand1, op=op, operand2=operand2, result=result)
    iraf.imarith.setParList(pars)
    if doAirmass:
        # Adjust FITS header
        with pf.open(operand1) as f:
            am1 = f[0].header['airmass']
        with pf.open(operand2) as f:
            am2 = f[0].header['airmass']

        of = pf.open(result)
        of[0].header['airmass1'] = am1
        of[0].header['airmass2'] = am2
        of.writeto(result, clobber=True)


def gunzip(A, B):
    if A.endswith(".gz"):
        os.system("gunzip %s" % A)
        A = os.path.splitext(A)[0]
    if B.endswith(".gz"):
        os.system("gunzip %s" % B)
        B = os.path.splitext(B)[0]

    return A,B


def gzip(A,B):
    if not A.endswith(".gz"):
        os.system("gzip %s" % A)
    if not B.endswith(".gz"):
        os.system("gzip %s" % B)

    return A+".gz", B+".gz"


def add(A,B, outname):
    A,B = gunzip(A,B)
    imarith(A, "+", B, outname)
    gzip(A,B)

    return pf.open(outname)


def addcon(A,B, outname):
    A,B = gunzip(A,B)
    imarith(A, "+", B, outname)
    gzip(A,"junk.gz")

    return pf.open(outname)


def subtract(A,B, outname):
    if os.path.exists(outname):
        return pf.open(outname)

    A,B = gunzip(A,B)
    imarith(A, "-", B, outname, doAirmass=True)
    A,B = gzip(A,B)

    return pf.open(outname)


def divide(A,B, outname):
    A,B = gunzip(A,B)
    imarith(A, "/", B, outname)
    gzip(A,B)

    return pf.open(outname)


def combines(A,B,C,D, outname):
    """ Creates outname with A+B+C+D """
    if os.path.exists(outname):
        return pf.open(outname)

    try: os.remove('AB.fits')
    except: pass
    try: os.remove('CD.fits')
    except: pass
    add(A,B, 'AB.fits')
    add(C,D, 'CD.fits')

    add('AB.fits', 'CD.fits', outname)
    try: os.remove('AB.fits')
    except: pass
    try: os.remove('CD.fits')
    except: pass


def combine4(A,B,C,D, outname):
    """Creates outname which is == A-(B+C+D)/3"""

    if os.path.exists(outname):
        return pf.open(outname)

    try: os.remove("APB.fits")
    except: pass
    add(A,B,"APB.fits")
    try: os.remove("3ABC.fits")
    except: pass
    add(B,C,"3ABC.fits")
    try: os.remove(outname)
    except: pass
    divide("3ABC.fits", "3", "ABC.fits")
    try: os.remove("3ABC.fits")
    except: pass
    try: os.remove(outname)
    except: pass
    subtract(A, "ABC.fits", outname)
    try: os.remove("ABC.fits")
    except: pass
    try: os.remove("APB.fits")
    except: pass

    return pf.open(outname)


def bgd_level(extractions):
    """Remove background from extractions"""

    levels = []
    for spectrum in extractions:
        if spectrum.__dict__.has_key('spec') and spectrum.spec is not None \
            and spectrum.lamcoeff is not None:

            l, Fl = spectrum.get_counts(the_spec='specw')

            levels.append(np.median(Fl))

    bgd = np.median(levels)
    sd = np.std(levels)
    pl.plot(levels,'x')
    pl.axhline(bgd)
    pl.axhline(bgd+sd)
    pl.axhline(bgd-sd)
    pl.ylim(-20*sd-bgd,20*sd-bgd)
    pl.show()


def handle_extract(data, outname=None, fine='fine.npy',flexure_x_corr_nm=0.0,
    flexure_y_corr_pix = 0.0):

    exfile = "extracted_%s.npy" % outname
    if not os.path.exists(outname + ".npy"):
        E = Wavelength.wavelength_extract(data, fine, filename=outname,
            flexure_x_corr_nm = flexure_x_corr_nm,
            flexure_y_corr_pix= flexure_y_corr_pix,
            flat_corrections=flat_corrections)

        np.save(exfile, [E, meta])
        print "Wrote %s.npy" % exfile
    else:
        E, meta = np.load(exfile)

    return E


def handle_Flat(A, fine, outname=None):
    """Loads IFU Flat frame "A" and extracts spectra using "fine".

    Args:
        A (string): filename of ifu FITS file to extract from.
        fine (string): filename of NumPy file with locations + wavelength soln.
        outname (string): filename to write results to.

    Returns:
        None
    Raises:
        None
    """

    fine, fmeta = np.load(fine)
    if outname is None:
        outname = "%s" % (A)

    if os.path.isfile(outname+".npy"):
        print "Extractions already exist in %s.npy!" % outname
        print "rm %s.npy # if you want to recreate extractions" % outname
    else:
        print "\nCREATING extractions ..."
        spec = pf.open(A)

        print "\nExtracting object spectra"
        E, meta = Wavelength.wavelength_extract(spec, fine, filename=outname,
            flexure_x_corr_nm=0., flexure_y_corr_pix=0.)
        meta['airmass'] = spec[0].header['airmass']
        header = {}
        for k,v in spec[0].header.iteritems():
            try: header[k] = v
            except: pass
        meta['HA'] = header['HA'] if 'HA' in header else header['TEL_HA']
        meta['DEC'] = header['DEC'] if 'DEC' in header else header['TEL_DEC']
        meta['RA'] = header['RA'] if 'RA' in header else header['TEL_RA']
        meta['PRLLTC'] = header['PRLLTC'] if 'PRLLTC' in header else header['TEL_PA']
        meta['EQUINOX'] = header['EQUINOX'] if 'EQUINOX' in header else header['TELEQX']
        if 'UTC' in header:
            meta['utc'] = header['UTC']
        else:
            tjd = Time(header['JD'], format='jd', scale='utc')
            meta['utc'] = tjd.yday
        meta['fiducial_wavelength'] = fmeta['fiducial_wavelength']

        meta['header'] = header

        meta['exptime'] = spec[0].header['exptime']
        np.save(outname, [E, meta])
        print "Wrote %s.npy" % outname


def handle_Std(A, fine, outname=None, standard=None, Aoffset=None, 
                flat_corrections=None, lmin=650, lmax=700):
    """Loads IFU frame "A" and extracts standard star spectra using "fine".

    Args:
        A (string): filename of ifu FITS file to extract from.
        fine (string): filename of NumPy file with locations + wavelength soln
        outname (string): filename to write results to
        standard (string): name of standard star
        Aoffset (2tuple): X (nm)/Y (pix) shift to apply for flexure correction
        flat_corrections (list): A list of FlatCorrection objects for
            correcting the extraction

    Returns:
        The extracted spectrum, a dictionary:
        {'ph_10m_nm': Observed flux in photon / 10 m / nm integrated
        'nm': Wavelength solution in nm
        'N_spax': Total number of spaxels that created ph_10m_nm
        'skyph': Sky flux in photon / 10 m / nanometer / spaxel
        'std-correction': ratio of observed to reference flux
        'std-maxnm': maximum reference wavelength in nm
        'radius_as': Extraction radius in arcsec
        'pos': X/Y extraction location of spectrum in arcsec}

    Raises:
        None
    """

    # Load wavelength/spatial solution
    fine, fmeta = np.load(fine)
    # Set a default outname if needed
    if outname is None:
        outname = "%s" % (A)
    # Check for flexure offsets
    if Aoffset is not None:
        ff = np.load(Aoffset)
        flexure_x_corr_nm = ff[0]['dXnm']
        flexure_y_corr_pix = ff[0]['dYpix']
        print "Dx %2.1f nm | Dy %2.1f px" % (ff[0]['dXnm'], ff[0]['dYpix'])
    else:
        flexure_x_corr_nm = 0
        flexure_y_corr_pix = 0
    # The spaxel extraction already exist, so load them in
    if os.path.isfile(outname+".npy"):
        print "USING extractions in %s.npy!" % outname
        print "rm %s.npy # if you want to recreate extractions" % outname
        E, meta = np.load(outname+".npy")
        E_var, meta_var = np.load("var_" + outname + ".npy")
    # No extractions yet, so generate them
    else:
        print "\nCREATING extractions ..."
        # Load spectrum image
        spec = pf.open(A)
        # Set up variance image by adding read noise to Poisson noise
        adcspeed = spec[0].header["ADCSPEED"]
        if adcspeed == 2: read_var = 22*22
        else: read_var = 5*5
        # Variance image is input image plus read variance
        var = addcon(A, str(read_var), "var_" + outname + ".fits")
        # Extract each object spaxel
        print "\nExtracting object spectra"
        E, meta = Wavelength.wavelength_extract(spec, fine, 
            filename=outname,
            flexure_x_corr_nm=flexure_x_corr_nm,
            flexure_y_corr_pix=flexure_y_corr_pix,
            flat_corrections=flat_corrections)
        # Extract metadata
        meta['airmass'] = spec[0].header['airmass']
        header = {}
        for k,v in spec[0].header.iteritems():
            try: header[k] = v
            except: pass
        meta['HA'] = header['HA'] if 'HA' in header else header['TEL_HA']
        meta['DEC'] = header['DEC'] if 'DEC' in header else header['TEL_DEC']
        meta['RA'] = header['RA'] if 'RA' in header else header['TEL_RA']
        meta['PRLLTC'] = header['PRLLTC'] if 'PRLLTC' in header else header['TEL_PA']
        meta['EQUINOX'] = header['EQUINOX'] if 'EQUINOX' in header else header['TELEQX']
        if 'UTC' in header:
            meta['utc'] = header['UTC']
        else:
            tjd = Time(header['JD'], format='jd', scale='utc')
            meta['utc'] = tjd.yday
        meta['fiducial_wavelength'] = fmeta['fiducial_wavelength']
        meta['header'] = header
        meta['exptime'] = spec[0].header['exptime']
        # Save object extraction
        np.save(outname, [E, meta])
        print "Wrote %s.npy" % outname
        # Extract each variance spaxel
        print "\nExtracting variance spectra"
        E_var, meta_var = Wavelength.wavelength_extract(var, fine,
            filename=outname,
            flexure_x_corr_nm=flexure_x_corr_nm,
            flexure_y_corr_pix=flexure_y_corr_pix,
            flat_corrections=flat_corrections)
        # Save variance extraction
        np.save("var_" + outname, [E_var, meta_var])
        print "Wrote var_%s.npy" % outname

    # Get the object name of record
    object = meta['header']['OBJECT'].split()[0]

    # Automatic extraction using Gaussian fit for Standard Stars
    sixA, posA, adcpos, radius_used = identify_spectra_Gauss_fit(E,
            outname=outname, PRLLTC=Angle(meta['PRLLTC'], unit='deg'),
            lmin=lmin, lmax=lmax, airmass=meta['airmass'])
    # Use all sky spaxels in image for Standard Stars
    kixA = identify_sky_spectra(E, posA, inner=radius_used*1.1)

    # Make an image of the spaxels for the record
    to_image(E, meta, outname, posA=posA, adcpos=adcpos)
    # get the mean spectrum over the selected spaxels
    resA = interp_spectra(E, sixA, outname=outname+".pdf")
    skyA = interp_spectra(E, kixA, outname=outname+"_sky.pdf")
    varA = interp_spectra(E_var, sixA, outname=outname+"_var.pdf")
    ## Plot out the X/Y positions of the selected spaxels
    XSA = []
    YSA = []
    XSK = []
    YSK = []
    for ix in sixA:
        XSA.append(E[ix].X_as)
        YSA.append(E[ix].Y_as)
    for ix in kixA:
        XSK.append(E[ix].X_as)
        YSK.append(E[ix].Y_as)

    pl.figure()
    pl.clf()
    pl.ylim(-20,20)
    pl.xlim(-22,20)
    pl.grid(True)
    if posA is not None:
        pl.axvline(posA[0], color='black', linewidth=.5)
        pl.axhline(posA[1], color='black', linewidth=.5)
    pl.xlabel("X [as] @ %6.1f nm" % meta['fiducial_wavelength'])
    pl.ylabel("Y [as]")
    pl.scatter(XSA,YSA, color='red', marker='H', s=50, linewidth=0)
    pl.scatter(XSK,YSK, color='green', marker='H', s=50, linewidth=0)
    pl.title("%d selected spaxels for %s" % (len(XSA), object))
    pl.savefig("XYs_%s.pdf" % outname)
    pl.close()
    print "Wrote XYs_%s.pdf" % outname
    # / End Plot

    # Define our standard wavelength grid
    ll = Wavelength.fiducial_spectrum()
    # Resample sky onto standard wavelength grid
    sky_A = interp1d(skyA[0]['nm'], skyA[0]['ph_10m_nm'], bounds_error=False)
    sky = sky_A(ll)
    # Resample variance onto standard wavelength grid
    var_A = interp1d(varA[0]['nm'], varA[0]['ph_10m_nm'], bounds_error=False)
    varspec = var_A(ll)
    # Copy and resample object spectrum onto standard wavelength grid
    res = np.copy(resA)
    res = [{"doc": resA[0]["doc"], "ph_10m_nm": np.copy(resA[0]["ph_10m_nm"]),
        "spectra": np.copy(resA[0]["spectra"]),
        "coefficients": np.copy(resA[0]["coefficients"]),
        "nm": np.copy(resA[0]["ph_10m_nm"])}]
    res[0]['nm'] = np.copy(ll)
    f1 = interp1d(resA[0]['nm'], resA[0]['ph_10m_nm'], bounds_error=False)
    # Calculate airmass correction
    airmass = meta['airmass']
    extCorr = 10**(Atm.ext(ll*10) * airmass/2.5)
    print "Median airmass corr: %.4f" % np.median(extCorr)
    # Calculate output corrected spectrum
    # Account for sky, airmass and aperture
    res[0]['ph_10m_nm'] = (f1(ll)-sky_A(ll)) * extCorr * len(sixA)

    # Process standard star objects
    print "STANDARD"
    # Extract reference data
    wav = standard[:,0]/10.0
    flux = standard[:,1]
    # Calculate/Interpolate correction onto object wavelengths
    fun = interp1d(wav, flux, bounds_error=False, fill_value = np.nan)
    correction0 = fun(res[0]['nm'])/res[0]['ph_10m_nm']
    # Filter for resolution
    flxf = filters.gaussian_filter(flux,19.)
    # Calculate/Interpolate filtered correction
    fun = interp1d(wav, flxf, bounds_error=False, fill_value = np.nan)
    correction = fun(res[0]['nm'])/res[0]['ph_10m_nm']
    # Use unfiltered for H-beta region
    ROI = (res[0]['nm'] > 470.) & (res[0]['nm'] < 600.)
    correction[ROI] = correction0[ROI]
    # Store correction and max calibrated wavelength
    res[0]['std-correction'] = correction
    res[0]['std-maxnm'] = np.max(wav)

    # Store new metadata
    res[0]['exptime'] = meta['exptime']
    res[0]['Extinction Correction'] = 'Applied using Hayes & Latham'
    res[0]['extinction_corr'] = extCorr
    res[0]['skyph'] = sky * len(sixA)
    res[0]['skynm'] = ll
    res[0]['var'] = varspec
    res[0]['radius_as'] = radius_used
    res[0]['position'] = posA
    res[0]['N_spax'] = len(sixA)
    res[0]['meta'] = meta
    res[0]['object_spaxel_ids'] = sixA
    res[0]['sky_spaxel_ids'] = kixA
    res[0]['sky_spectra'] = skyA[0]['spectra']
    # Calculate wavelength offsets
    coef = chebfit(np.arange(len(ll)), ll, 4)
    xs = np.arange(len(ll)+1)
    newll = chebval(xs, coef)
    # Store offsets
    res[0]['dlam'] = np.diff(newll)
    # Save the final spectrum
    np.save("sp_" + outname, res)
    print "Wrote sp_"+outname+".npy"


def handle_A(A, fine, outname=None, standard=None, Aoffset=None, radius=2, 
                flat_corrections=None, nosky=False, lmin=650, lmax=700):
    """Loads IFU frame "A" and extracts spectra using "fine".

    Args:
        A (string): filename of ifu FITS file to extract from.
        fine (string): filename of NumPy file with locations + wavelength
            soln
        outname (string): filename to write results to
        Aoffset (2tuple): X (nm)/Y (pix) shift to apply for flexure correction
        radius (float): Extraction radius in arcsecond
        flat_corrections (list): A list of FlatCorrection objects for
            correcting the extraction
        nosky (Boolean): if True don't subtract sky, merely sum in aperture

    Returns:
        The extracted spectrum, a dictionary:
        {'ph_10m_nm': Flux in photon / 10 m / nanometer integrated
        'nm': Wavelength solution in nm
        'N_spax': Total number of spaxels that created ph_10m_nm
        'skyph': Sky flux in photon / 10 m / nanometer / spaxel
        'radius_as': Extraction radius in arcsec
        'pos': X/Y extraction location of spectrum in arcsec}

    Raises:
        None
    """

    # Load wavelength/spatial solution
    fine, fmeta = np.load(fine)
    # Set a default outname if needed
    if outname is None:
        outname = "%s" % (A)
    # Check for flexure offsets
    if Aoffset is not None:
        ff = np.load(Aoffset)
        flexure_x_corr_nm = ff[0]['dXnm']
        flexure_y_corr_pix = ff[0]['dYpix']
        print "Dx %2.1f nm | Dy %2.1f px" % (ff[0]['dXnm'], ff[0]['dYpix'])
    else:
        flexure_x_corr_nm = 0
        flexure_y_corr_pix = 0
    # The spaxel extraction already exist, so load them in
    if os.path.isfile(outname+".npy"):
        print "USING extractions in %s.npy!" % outname
        print "rm %s.npy # if you want to recreate extractions" % outname
        E, meta = np.load(outname+".npy")
        E_var, meta_var = np.load("var_" + outname + ".npy")
    # No extractions yet, so generate them
    else:
        print "\nCREATING extractions ..."
        # Load spectrum image
        spec = pf.open(A)
        # Set up variance image by adding read noise to Poisson noise
        adcspeed = spec[0].header["ADCSPEED"]
        if adcspeed == 2: read_var = 22*22
        else: read_var = 5*5
        # Variance image is input image plus read variance
        var = addcon(A, str(read_var), "var_" + outname + ".fits")
        # Extract each object spaxel
        print "\nExtracting object spectra"
        E, meta = Wavelength.wavelength_extract(spec, fine, 
            filename=outname,
            flexure_x_corr_nm=flexure_x_corr_nm,
            flexure_y_corr_pix=flexure_y_corr_pix,
            flat_corrections=flat_corrections)
        # Extract metadata
        meta['airmass'] = spec[0].header['airmass']
        header = {}
        for k,v in spec[0].header.iteritems():
            try: header[k] = v
            except: pass
        meta['HA'] = header['HA'] if 'HA' in header else header['TEL_HA']
        meta['DEC'] = header['DEC'] if 'DEC' in header else header['TEL_DEC']
        meta['RA'] = header['RA'] if 'RA' in header else header['TEL_RA']
        meta['PRLLTC'] = header['PRLLTC'] if 'PRLLTC' in header else header['TEL_PA']
        meta['EQUINOX'] = header['EQUINOX'] if 'EQUINOX' in header else header['TELEQX']
        if 'UTC' in header:
            meta['utc'] = header['UTC']
        else:
            tjd = Time(header['JD'], format='jd', scale='utc')
            meta['utc'] = tjd.yday
        meta['fiducial_wavelength'] = fmeta['fiducial_wavelength']
        meta['header'] = header
        meta['exptime'] = spec[0].header['exptime']
        # Save object extraction
        np.save(outname, [E, meta])
        print "Wrote %s.npy" % outname
        # Extract each variance spaxel
        print "\nExtracting variance spectra"
        E_var, meta_var = Wavelength.wavelength_extract(var, fine,
            filename=outname,
            flexure_x_corr_nm=flexure_x_corr_nm,
            flexure_y_corr_pix=flexure_y_corr_pix,
            flat_corrections=flat_corrections)
        # Save variance extraction
        np.save("var_" + outname, [E_var, meta_var])
        print "Wrote var_%s.npy" % outname

    # Get the object name of record
    object = meta['header']['OBJECT'].split()[0]

    # Automatic extraction using Gaussian fit for Standard Stars
    if standard is not None:
        sixA, posA, adcpos, radius_used = identify_spectra_Gauss_fit(E,
                outname=outname, PRLLTC=Angle(meta['PRLLTC'], unit='deg'),
                lmin=lmin, lmax=lmax, airmass=meta['airmass'])
        # Use all sky spaxels in image for Standard Stars
        kixA = identify_sky_spectra(E, posA, inner=radius_used*1.1)
    # A single-frame Science Object
    else:
        sixA, posA, adcpos, radius_used = identify_spectra_gui(E, radius=radius,
            object=object, PRLLTC=Angle(meta['PRLLTC'], unit='deg'),
            lmin=lmin, lmax=lmax, airmass=meta['airmass'])
        # Use an annulus for sky spaxels for Science Objects
        kixA = identify_bgd_spectra(E, posA, inner=radius_used*1.1)

    # Make an image of the spaxels for the record
    to_image(E, meta, outname, posA=posA, adcpos=adcpos)
    # get the mean spectrum over the selected spaxels
    resA = interp_spectra(E, sixA, outname=outname+".pdf")
    skyA = interp_spectra(E, kixA, outname=outname+"_sky.pdf")
    varA = interp_spectra(E_var, sixA, outname=outname+"_var.pdf")
    ## Plot out the X/Y positions of the selected spaxels
    XSA = []
    YSA = []
    XSK = []
    YSK = []
    for ix in sixA:
        XSA.append(E[ix].X_as)
        YSA.append(E[ix].Y_as)
    for ix in kixA:
        XSK.append(E[ix].X_as)
        YSK.append(E[ix].Y_as)

    pl.figure()
    pl.clf()
    pl.ylim(-20,20)
    pl.xlim(-22,20)
    pl.grid(True)
    if posA is not None:
        pl.axvline(posA[0], color='black', linewidth=.5)
        pl.axhline(posA[1], color='black', linewidth=.5)
    pl.xlabel("X [as] @ %6.1f nm" % meta['fiducial_wavelength'])
    pl.ylabel("Y [as]")
    pl.scatter(XSA,YSA, color='red', marker='H', s=50, linewidth=0)
    pl.scatter(XSK,YSK, color='green', marker='H', s=50, linewidth=0)
    pl.title("%d selected spaxels for %s" % (len(XSA), object))
    pl.savefig("XYs_%s.pdf" % outname)
    print "Wrote XYs_%s.pdf" % outname
    pl.close()
    # / End Plot

    # Define our standard wavelength grid
    ll = Wavelength.fiducial_spectrum()
    # Resample sky onto standard wavelength grid
    sky_A = interp1d(skyA[0]['nm'], skyA[0]['ph_10m_nm'], bounds_error=False)
    sky = sky_A(ll)
    # Resample variance onto standard wavelength grid
    var_A = interp1d(varA[0]['nm'], varA[0]['ph_10m_nm'], bounds_error=False)
    varspec = var_A(ll)
    # Copy and resample object spectrum onto standard wavelength grid
    res = np.copy(resA)
    res = [{"doc": resA[0]["doc"], "ph_10m_nm": np.copy(resA[0]["ph_10m_nm"]),
        "spectra": np.copy(resA[0]["spectra"]),
        "coefficients": np.copy(resA[0]["coefficients"]),
        "nm": np.copy(resA[0]["ph_10m_nm"])}]
    res[0]['nm'] = np.copy(ll)
    f1 = interp1d(resA[0]['nm'], resA[0]['ph_10m_nm'], bounds_error=False)
    # Calculate airmass correction
    airmass = meta['airmass']
    extCorr = 10**(Atm.ext(ll*10) * airmass/2.5)
    print "Median airmass corr: %.4f" % np.median(extCorr)
    # Calculate output corrected spectrum
    if nosky:
        # Account for airmass and aperture
        res[0]['ph_10m_nm'] = f1(ll) * extCorr * len(sixA)
    else:
        # Account for sky, airmass and aperture
        res[0]['ph_10m_nm'] = (f1(ll)-sky_A(ll)) * extCorr * len(sixA)

    # Store new metadata
    res[0]['exptime'] = meta['exptime']
    res[0]['Extinction Correction'] = 'Applied using Hayes & Latham'
    res[0]['extinction_corr'] = extCorr
    res[0]['skyph'] = sky * len(sixA)
    res[0]['skynm'] = ll
    res[0]['var'] = varspec
    res[0]['radius_as'] = radius_used
    res[0]['position'] = posA
    res[0]['N_spax'] = len(sixA)
    res[0]['meta'] = meta
    res[0]['object_spaxel_ids'] = sixA
    res[0]['sky_spaxel_ids'] = kixA
    res[0]['sky_spectra'] = skyA[0]['spectra']
    # Calculate wavelength offsets
    coef = chebfit(np.arange(len(ll)), ll, 4)
    xs = np.arange(len(ll)+1)
    newll = chebval(xs, coef)
    # Store offsets
    res[0]['dlam'] = np.diff(newll)
    # Save the final spectrum
    np.save("sp_" + outname, res)
    print "Wrote sp_"+outname+".npy"


def handle_AB(A, B, fine, outname=None, Aoffset=None, Boffset=None, 
        radius=2, flat_corrections=None, nosky=False, lmin=650, lmax=700):
    """Loads IFU frame "A" and "B" and extracts A-B spectra using "fine".

    Args:
        A (string): filename of ifu FITS file to extract from.
        B (string): filename of ifu FITS file to extract from.
        fine (string): filename of NumPy file with locations + wavelength soln.
        outname (string): filename to write results to
        Aoffset (2tuple): X (nm)/Y (pix) shift to apply for flexure correction
        Boffset (2tuple): X (nm)/Y (pix) shift to apply for flexure correction
        radius (float): Extraction radius in arcsecond
        flat_corrections (list): A list of FlatCorrection objects for
            correcting the extraction
        nosky (Boolean): if True don't subtract sky, merely sum in aperture

    Returns:
        The extracted spectrum, a dictionary:
        {'ph_10m_nm': Flux in photon / 10 m / nanometer integrated
        'var'
        'nm': Wavelength solution in nm
        'N_spaxA': Total number of "A" spaxels
        'N_spaxB': Total number of "B" spaxels
        'skyph': Sky flux in photon / 10 m / nanometer / spaxel
        'radius_as': Extraction radius in arcsec
        'pos': X/Y extraction location of spectrum in arcsec}

    Raises:
        None
    """

    fine, fmeta = np.load(fine)
    if outname is None:
        outname = "%sm%s" % (A,B)

    if Aoffset is not None:
        ff = np.load(Aoffset)
        flexure_x_corr_nm = ff[0]['dXnm']
        flexure_y_corr_pix = -ff[0]['dYpix']

        print "Dx %2.1f nm | Dy %2.1f px" % (ff[0]['dXnm'], ff[0]['dYpix'])
    else:
        flexure_x_corr_nm = 0
        flexure_y_corr_pix = 0

    if os.path.isfile(outname + ".npy"):
        print "USING extractions in %s!" % outname
        print "rm %s.npy # if you want to recreate extractions" % outname
        E, meta = np.load(outname + ".npy")
        E_var, meta_var = np.load("var_" + outname + ".npy")
        header = meta['header']
    else:
        print "\nCREATING extractions ..."
        diff = subtract(A,B, outname + ".fits")
        add(A,B, "tmpvar_" + outname + ".fits")

        adcspeed = diff[0].header["ADCSPEED"]
        if adcspeed == 2: read_var = 22*22
        else: read_var = 5*5

        var = addcon("tmpvar_" + outname + ".fits", str(read_var), 
                        "var_" + outname + ".fits")
        os.remove("tmpvar_" + outname + ".fits.gz")

        print "\nExtracting object spectra"
        E, meta = Wavelength.wavelength_extract(diff, fine,
            filename=outname,
            flexure_x_corr_nm = flexure_x_corr_nm,
            flexure_y_corr_pix = flexure_y_corr_pix,
            flat_corrections=flat_corrections)
        meta['airmass1'] = diff[0].header['airmass1']
        meta['airmass2'] = diff[0].header['airmass2']
        meta['airmass'] = diff[0].header['airmass']
        header = {}
        for k,v in diff[0].header.iteritems():
            try: header[k] = v
            except: pass
        meta['HA'] = header['HA'] if 'HA' in header else header['TEL_HA']
        meta['DEC'] = header['DEC'] if 'DEC' in header else header['TEL_DEC']
        meta['RA'] = header['RA'] if 'RA' in header else header['TEL_RA']
        meta['PRLLTC'] = header['PRLLTC'] if 'PRLLTC' in header else header['TEL_PA']
        meta['EQUINOX'] = header['EQUINOX'] if 'EQUINOX' in header else header['TELEQX']
        if 'UTC' in header:
            meta['utc'] = header['UTC']
        else:
            tjd = Time(header['JD'], format='jd', scale='utc')
            meta['utc'] = tjd.yday
        meta['fiducial_wavelength'] = fmeta['fiducial_wavelength']

        meta['header'] = header

        meta['exptime'] = diff[0].header['exptime']
        np.save(outname, [E, meta])
        print "Wrote %s.npy" % outname

        print "\nExtracting variance spectra"
        E_var, meta_var = Wavelength.wavelength_extract(var, fine,
            filename=outname,
            flexure_x_corr_nm = flexure_x_corr_nm,
            flexure_y_corr_pix = flexure_y_corr_pix,
            flat_corrections=flat_corrections)

        np.save("var_" + outname, [E_var, meta_var])
        print "Wrote var_%s.npy" % outname

    object = header['OBJECT'].split()[0]

    print "\nMark positive (red) target first"
    sixA, posA, adc_A, radius_used_A = \
            identify_spectra_gui(E, radius=radius,
                                 PRLLTC=Angle(meta['PRLLTC'], unit='deg'),
                                 lmin=lmin, lmax=lmax, object=object, 
                                 airmass=meta['airmass'])
    print "\nMark negative (blue) target next"
    sixB, posB, adc_B, radius_used_B = \
            identify_spectra_gui(E, radius=radius_used_A,
                                 PRLLTC=Angle(meta['PRLLTC'], unit='deg'),
                                 lmin=lmin, lmax=lmax, object=object, 
                                 airmass=meta['airmass'])

    to_image(E, meta, outname, posA=posA, posB=posB, adcpos=adc_A)

    kixA = identify_bgd_spectra(E, posA, inner=radius_used_A*1.1)
    kixB = identify_bgd_spectra(E, posB, inner=radius_used_B*1.1)

    resA = interp_spectra(E, sixA, sign=1, outname=outname+"_A.pdf")
    resB = interp_spectra(E, sixB, sign=-1, outname=outname+"_B.pdf")
    skyA = interp_spectra(E, kixA, sign=1, outname=outname+"_skyA.pdf")
    skyB = interp_spectra(E, kixB, sign=-1, outname=outname+"_skYB.pdf")
    varA = interp_spectra(E_var, sixA, sign=1, outname=outname+"_A_var.pdf")
    varB = interp_spectra(E_var, sixB, sign=1, outname=outname+"_B_var.pdf")

    # Plot out the X/Y selected spectra
    XSA = []
    YSA = []
    XSB = []
    YSB = []
    XKA = []
    YKA = []
    XKB = []
    YKB = []
    for ix in sixA:
        XSA.append(E[ix].X_as)
        YSA.append(E[ix].Y_as)
    for ix in sixB:
        XSB.append(E[ix].X_as)
        YSB.append(E[ix].Y_as)
    for ix in kixA:
        XKA.append(E[ix].X_as)
        YKA.append(E[ix].Y_as)
    for ix in kixB:
        XKB.append(E[ix].X_as)
        YKB.append(E[ix].Y_as)

    pl.figure()
    pl.clf()
    pl.ylim(-20,20)
    pl.xlim(-22,20)
    pl.grid(True)
    if posA is not None:
        pl.axvline(posA[0], color='black', linewidth=.5)
        pl.axhline(posA[1], color='black', linewidth=.5)
    if posB is not None:
        pl.axvline(posB[0], color='black', linewidth=.5)
        pl.axhline(posB[1], color='black', linewidth=.5)
    pl.xlabel("X [as] @ %6.1f nm" % meta['fiducial_wavelength'])
    pl.ylabel("Y [as]")
    pl.scatter(XSA,YSA, color='blue', marker='H', s=50, linewidth=0)
    pl.scatter(XSB,YSB, color='red', marker='H', s=50, linewidth=0)
    pl.scatter(XKA,YKA, color='green', marker='H', s=50, linewidth=0)
    pl.scatter(XKB,YKB, color='green', marker='H', s=50, linewidth=0)
    pl.savefig("XYs_%s.pdf" % outname)
    print "Wrote XYs_%s.pdf" % outname
    pl.close()
    # / End Plot

    np.save("sp_A_" + outname, resA)
    np.save("sp_B_" + outname, resB)
    np.save("var_A_" + outname, varA)
    np.save("var_B_" + outname, varB)
    print("Wrote sp_A_%s.npy, sp_B_%s.npy, var_A_%s.npy, var_B_%s.npy" %
            (outname, outname, outname, outname))

    ll = Wavelength.fiducial_spectrum()
    sky_A = interp1d(skyA[0]['nm'], skyA[0]['ph_10m_nm'], bounds_error=False)
    sky_B = interp1d(skyB[0]['nm'], skyB[0]['ph_10m_nm'], bounds_error=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        sky = np.nanmean([sky_A(ll), sky_B(ll)], axis=0)

    var_A = interp1d(varA[0]['nm'], varA[0]['ph_10m_nm'], bounds_error=False)
    var_B = interp1d(varB[0]['nm'], varB[0]['ph_10m_nm'], bounds_error=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        varspec = np.nanmean([var_A(ll), var_B(ll)], axis=0) * (len(sixA) + 
                                                                    len(sixB))

    res = np.copy(resA)
    res = [{"doc": resA[0]["doc"], "ph_10m_nm": np.copy(resA[0]["ph_10m_nm"]),
        "nm": np.copy(resA[0]["ph_10m_nm"])}]
    res[0]['nm'] = np.copy(ll)
    f1 = interp1d(resA[0]['nm'], resA[0]['ph_10m_nm'], bounds_error=False)
    f2 = interp1d(resB[0]['nm'], resB[0]['ph_10m_nm'], bounds_error=False)

    airmassA = meta['airmass1']
    airmassB = meta['airmass2']

    extCorrA = 10**(Atm.ext(ll*10)*airmassA/2.5)
    extCorrB = 10**(Atm.ext(ll*10)*airmassB/2.5)
    print("Median airmass corrs A: %.4f, B: %.4f" %
            (np.median(extCorrA), np.median(extCorrB)))
    # If requested merely sum in aperture, otherwise subtract sky
    if nosky:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            res[0]['ph_10m_nm'] = \
                np.nansum([
                f1(ll) * extCorrA,
                f2(ll) * extCorrB], axis=0) * \
                (len(sixA) + len(sixB))
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            res[0]['ph_10m_nm'] = \
                np.nansum([
                (f1(ll)-sky_A(ll)) * extCorrA,
                (f2(ll)-sky_B(ll)) * extCorrB], axis=0) * \
                (len(sixA) + len(sixB))

    res[0]['exptime'] = meta['exptime']
    res[0]['Extinction Correction'] = 'Applied using Hayes & Latham'
    res[0]['extinction_corr_A'] = extCorrA
    res[0]['extinction_corr_B'] = extCorrB
    res[0]['skyph'] = sky * (len(sixA) + len(sixB))
    res[0]['var'] = varspec
    res[0]['radius_as'] = radius_used_A
    res[0]['positionA'] = posA
    res[0]['positionB'] = posA
    res[0]['N_spaxA'] = len(sixA)
    res[0]['N_spaxB'] = len(sixB)
    res[0]['meta'] = meta
    res[0]['object_spaxel_ids_A'] = sixA
    res[0]['sky_spaxel_ids_A'] = skyA
    res[0]['object_spaxel_ids_B'] = sixB
    res[0]['sky_spaxel_ids_B'] = skyB

    coef = chebfit(np.arange(len(ll)), ll, 4)
    xs = np.arange(len(ll)+1)
    newll = chebval(xs, coef)

    res[0]['dlam'] = np.diff(newll)

    np.save("sp_" + outname, res)
    print "Wrote sp_"+outname+".npy"


def measure_flexure(sky):
    """ Measure expected (589.3 nm) - measured emission line in nm"""
    ll, ss = sky['nm'], sky['ph_10m_nm']

    pl.figure()
    pl.step(ll, ss)

    pix = SG.argrelmax(ss, order=20)[0]
    skynms = chebval(pix, sky['coefficients'])
    for s in skynms: pl.axvline(s)

    ixmin = np.argmin(np.abs(skynms - 589.3))
    dnm = 589.3 - skynms[ixmin]

    return dnm


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description=\
        """Extract a spectrum from an image using a geometric cube solution.
Handles a single A image and A+B pair as well as flat extraction.
        """, formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument('--A', type=str, help='FITS A file')
    parser.add_argument('--B', type=str, help='FITS B file')
    parser.add_argument('fine', type=str, help='Numpy fine wavelength solution')
    parser.add_argument('--outname', type=str, help='Prefix output name')
    parser.add_argument('--std', type=str, help='Name of standard')
    parser.add_argument('--Aoffset', type=str, 
                        help='Name of "A" flexure offset correction file')
    parser.add_argument('--Boffset', type=str, 
                        help='Name of "B" flexure offset correction file')
    parser.add_argument('--radius_as', type=float, 
                        help='Extraction radius in arcseconds', default=3)
    parser.add_argument('--flat_correction', type=str, 
                        help='Name of flat field .npy file', default=None)
    parser.add_argument('--nosky', action="store_true", default=False, 
                        help='No sky subtraction: only sum in aperture')
    parser.add_argument('--flat', action="store_true", default=False, 
                        help='Perform flat extraction')

    args = parser.parse_args()

    print ""

    if args.outname is not None:
        args.outname = os.path.splitext(args.outname)[0]

    if args.flat_correction is not None:
        print "Using flat data in %s" % args.flat_correction
        flat = np.load(args.flat_correction)
    else: flat = None

    if args.A is not None and args.B is not None:
        print "A B Extraction to %s.npy" % args.outname
        handle_AB(args.A, args.B, args.fine, outname=args.outname,
                    Aoffset=args.Aoffset, Boffset=args.Boffset,
                    radius=args.radius_as, flat_corrections=flat,
                    nosky=args.nosky)

    elif args.A is not None:
        if args.std is None:
            if args.flat:
                print "Flat Extraction to %s.npy" % args.outname
                handle_Flat(args.A, args.fine, outname=args.outname)
            else:
                print "Single Extraction to %s.npy" % args.outname
                handle_A(args.A, args.fine, outname=args.outname,
                            Aoffset=args.Aoffset, radius=args.radius_as,
                            flat_corrections=flat,nosky=args.nosky)
        else:
            print "Standard Star Extraction to %s.npy" % args.outname
            star = Stds.Standards[args.std]
            handle_Std(args.A, args.fine, outname=args.outname,
                        standard=star, Aoffset=args.Aoffset,
                        flat_corrections=flat)

    else:
        print "I do not understand your intent, you must specify --A, at least"
