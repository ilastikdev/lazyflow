###############################################################################
#   lazyflow: data flow based lazy parallel computation framework
#
#       Copyright (C) 2011-2014, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the Lesser GNU General Public License
# as published by the Free Software Foundation; either version 2.1
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# See the files LICENSE.lgpl2 and LICENSE.lgpl3 for full text of the
# GNU Lesser General Public License version 2.1 and 3 respectively.
# This information is also available on the ilastik web site at:
#		   http://ilastik.org/license/
###############################################################################
import os
import sys
import shutil
import tempfile

import numpy
import vigra

import lazyflow.graph
from lazyflow.operators.opReorderAxes import OpReorderAxes
from lazyflow.operators.operators import OpArrayCache
from lazyflow.operators.opArrayPiper import OpArrayPiper
from lazyflow.operators.ioOperators import OpExportMultipageTiff
from lazyflow.operators.ioOperators.opTiffReader import OpTiffReader

import logging
logger = logging.getLogger('tests.testOpMultipageTiff')

class TestOpMultipageTiff(object):

    def setUp(self):
        self.graph = lazyflow.graph.Graph()
        self._tmpdir = tempfile.mkdtemp()

        # Generate some test data
        self.dataShape = (1, 10, 64, 128, 2)
        self._axisorder = 'tzyxc'
        self.testData = vigra.VigraArray( self.dataShape,
                                         axistags=vigra.defaultAxistags(self._axisorder),
                                         order='C' ).astype(numpy.uint8)
        self.testData[...] = numpy.indices(self.dataShape).sum(0)

    def tearDown(self):
        # Clean up
        shutil.rmtree(self._tmpdir)
        
    def test_basic(self):
        opSource = OpArrayPiper(graph=self.graph)
        opSource.Input.setValue( self.testData )
        
        opData = OpArrayCache( graph=self.graph )
        opData.blockShape.setValue( self.testData.shape )
        opData.Input.connect( opSource.Output )
        
        filepath = os.path.join( self._tmpdir, 'multipage.tiff' )
        logger.debug( "writing to: {}".format(filepath) )
        
        opExport = OpExportMultipageTiff(graph=self.graph)
        opExport.Filepath.setValue( filepath )
        opExport.Input.connect( opData.Output )

        # Run the export
        opExport.run_export()

        opReader = OpTiffReader( graph=self.graph )
        opReader.Filepath.setValue( filepath )

        # Re-order before comparing
        opReorderAxes = OpReorderAxes( graph=self.graph )
        opReorderAxes.AxisOrder.setValue( self._axisorder )
        opReorderAxes.Input.connect( opReader.Output )
        
        readData = opReorderAxes.Output[:].wait()
        logger.debug("Expected shape={}".format( self.testData.shape ) )
        logger.debug("Read shape={}".format( readData.shape ) )
        
        assert opReorderAxes.Output.meta.shape == self.testData.shape, \
            "Exported files were of the wrong shape or number."
        assert (opReorderAxes.Output[:].wait() == self.testData.view( numpy.ndarray )).all(), \
            "Exported data was not correct"
        
        # Cleanup
        opReorderAxes.cleanUp()
        opReader.cleanUp()

if __name__ == "__main__":
    # Run this file independently to see debug output.
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    ioOpLogger = logging.getLogger('lazyflow.operators.ioOperators')
    ioOpLogger.addHandler( logging.StreamHandler(sys.stdout) )
    ioOpLogger.setLevel(logging.DEBUG)

    import sys
    import nose
    sys.argv.append("--nocapture")    # Don't steal stdout.  Show it on the console as usual.
    sys.argv.append("--nologcapture") # Don't set the logging level to DEBUG.  Leave it alone.
    nose.run(defaultTest=__file__)
