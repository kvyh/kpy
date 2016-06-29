# -*- coding: utf-8 -*-
"""
Created on Wed Jun 15 20:31:17 2016

@author: nadiablago
"""
import matplotlib
matplotlib.use("Agg")
import sextractor
import glob, os
import numpy as np
from astropy.coordinates import SkyCoord
from matplotlib import pylab as plt
import argparse
import pyfits as pf
import fitsutils
import datetime
import argparse
import logging

#Log into a file
FORMAT = '%(asctime)-15s %(levelname)s [%(name)s] %(message)s'
root_dir = "/scr2/sedm/logs/"
now = datetime.datetime.utcnow()
timestamp=datetime.datetime.isoformat(now)
timestamp=timestamp.split("T")[0]
logging.basicConfig(format=FORMAT, filename=os.path.join(root_dir, "listener_{0}.log".format(timestamp)), level=logging.INFO)
logger = logging.getLogger('flexure')
    

def run_flexure_test(sexfiles, plotdir):
    '''
    Compares the positions for the extracted lines for all the files given as a parameter.
    '''
    sexfiles.sort()
    posfiles = []
    
    logger.info("Running flexure test with %s files."%sexfiles)
    with open(os.path.join(plotdir, "flexure.log"), "w") as out:
        for sf in sexfiles:
            c = np.genfromtxt(sf)
            
            # We want bright sources.
            c = c[c[:,4]< -9]
            
            # We want round-shaped sources.
            c = c[c[:,8]<0.6]
            
            #Save the positions in a separate file with only X Y.
            np.savetxt(sf.replace(".sex", ".pos"), c[:,0:2])
            posfiles.append(sf.replace(".sex", ".pos"))
            
        c0 = np.genfromtxt(posfiles[0])
	i = 1
	while len(c0) ==0 and i<len(posfiles):
	    c0 = np.genfromtxt(posfiles[i])
	    i = i+1
	    
        flexure = []
        for f in posfiles[i:]:
            print f
            c1 = np.genfromtxt(f)
        
            c = SkyCoord(x=c0[:,0], y=c0[:,1], z=np.zeros(len(c0)), unit='m', representation='cartesian')
            catalog = SkyCoord(x=c1[:,0], y=c1[:,1], z=np.zeros(len(c1)), unit='m', representation='cartesian')#SkyCoord(x=c1[:0]*u.pixel, y=c1[:,1]*u.pixel, z=np.zeros(len(c0))*u.pixel, representation='cartesian')  
        
            #Now idx are indices into catalog that are the closest objects to each of the 
            #coordinates in c, d2d are the on-sky distances between them.
            idx, d2d, d3d = c.match_to_catalog_sky(catalog)  
            
            matches = catalog[idx]
            
            #Only consider it is a match if the distance is less than 10 pixels.
            matches = matches[d3d.value<10]
            d3d = d3d[d3d.value<10]

            #Add the flexure for plotting later.
            flexure.append(np.median(d3d.value))
            
            out.write("%s,%s,%.3f\n"%(os.path.basename(posfiles[0]), os.path.basename(f), np.median(d3d.value)))
            
            plt.hist(d3d, bins=50)
            plt.xlabel("Deviation [pixels]")
            plt.title("Median deviation: %.3f"%np.median(d3d.value))
            plt.savefig(os.path.join(plotdir, "%s_vs_%s.png"%(os.path.basename(posfiles[0]), os.path.basename(f))))
            plt.clf()
    
            plt.scatter(matches.x.value, matches.y.value, c=np.minimum(np.mean(d3d.value)+2*np.std(d3d.value), d3d.value))
            c = plt.colorbar()
            c.set_label("Deviation [pixels]")
            plt.savefig(os.path.join(plotdir, "%s_vs_%s_XY.png"%(os.path.basename(posfiles[0]), os.path.basename(f))))
            plt.clf()
            
        plt.plot(flexure)
        plt.xlabel("Exposure number")
        plt.ylabel("Median (flexure) [pixels]")
        plt.savefig(os.path.join(plotdir, "flexure.png"))
        plt.clf()

     
if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(description=\
        '''

        Runs astrometry.net on the image specified as a parameter and returns 
        the offset needed to be applied in order to center the object coordinates 
        in the reference pixel.
            
        ''', formatter_class=argparse.RawTextHelpFormatter)


    parser.add_argument('-d', dest="raw", type=str, help='Directory containing the raw fits for the night.', default=None)

    args = parser.parse_args()
    
    raw = args.raw
    
    if (raw is None):
        timestamp=datetime.datetime.isoformat(datetime.datetime.utcnow())
        timestamp = timestamp.split("T")[0].replace("-","")
        raw = os.path.join("/scr2/sedm/phot/", timestamp)
    
    files = glob.glob(os.path.join(raw, "ifu*fits"))
    #files_hg = [f for f in files if "Calib:  Hg" in get_par(f, "OBJECT")]
    files_hg = [f for f in files if fitsutils.has_par(f, "OBJECT") and "Calib:  Hg" in fitsutils.get_par(f, "OBJECT")]
    
    logger.info("Found the following Hg files: %s"%files_hg)
    if (len(files_hg)>1):
	files_hg.sort()
        sexfiles = sextractor.run_sex(files_hg, mask=False)
            
        plotdir = os.path.join(raw, "stats")
        if (not os.path.isdir(plotdir)):
            os.makedirs(plotdir)
                
        run_flexure_test(sexfiles, plotdir=plotdir)
