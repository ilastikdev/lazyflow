"""High-level API.

"""
from volumina.pixelpipeline.datasources import *
from volumina.layer import *
from volumina.layerstack import LayerStackModel
from volumina.volumeEditor import VolumeEditor
from volumina.imageEditor import ImageEditor
from volumina.imageEditorWidget import ImageEditorWidget
from volumina.volumeEditorWidget import VolumeEditorWidget

from PyQt4.QtCore import QRectF
from PyQt4.QtGui import QMainWindow, QApplication, QIcon, QAction, qApp, \
    QImage, QPainter
from PyQt4.uic import loadUi
import volumina.icons_rc

import os
import sys
import numpy
import colorsys
import random
import vigra

haveLazyflow = True
try:
    from volumina.io import Op5ifyer
except ImportError:
    haveLazyflow = False
from volumina.io import Array5d

#******************************************************************************
# V i e w e r                                                                 *
#******************************************************************************

class Viewer(QMainWindow):
    """High-level API to view multi-dimensional arrays.

    Properties:
        title -- window title

    """

    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        uiDirectory = os.path.split(volumina.__file__)[0]
        if uiDirectory == '':
            uiDirectory = '.'
        loadUi(uiDirectory + '/viewer.ui', self)

        self._dataShape = None
        self.editor = None

        self.actionQuit.triggered.connect(qApp.quit)
        #when connecting in renderScreenshot to a partial(...) function,
        #we need to remember the created function to be able to disconnect
        #to it later
        self._renderScreenshotDisconnect = None

        self.layerstack = LayerStackModel()
        self.layerWidget.init(self.layerstack)
        model = self.layerstack
        self.UpButton.clicked.connect(model.moveSelectedUp)
        model.canMoveSelectedUp.connect(self.UpButton.setEnabled)
        self.DownButton.clicked.connect(model.moveSelectedDown)
        model.canMoveSelectedDown.connect(self.DownButton.setEnabled)
        self.DeleteButton.clicked.connect(model.deleteSelected)
        model.canDeleteSelected.connect(self.DeleteButton.setEnabled)

        self.actionCurrentView = QAction(QIcon(), \
            "Only for selected view", self.menuView)
        f = self.actionCurrentView.font()
        f.setBold(True)
        self.actionCurrentView.setFont(f)


    def renderScreenshot(self, axis, blowup=1, filename="/tmp/volumina_screenshot.png"):
        """Save the complete slice as shown by the slice view 'axis'
        in the GUI as an image
        
        axis -- 0, 1, 2 (x, y, or z slice view)
        blowup -- enlarge written image by this factor
        filename -- output file
        """

        print "Rendering screenshot for axis=%d to '%s'" % (axis, filename)
        s = self.editor.imageScenes[axis]
        self.editor.navCtrl.enableNavigation = False
        func = partial(self._renderScreenshot, s, blowup, filename)
        self._renderScreenshotDisconnect = func
        s._renderThread.patchAvailable.connect(func)
        nRequested = 0
        for patchNumber in range(len(s._tiling)):
            p = s.tileProgress(patchNumber)
            if p < 1.0:
                s.requestPatch(patchNumber)
                nRequested += 1
        print "  need to compute %d of %d patches" % (nRequested, len(s._tiling))
        if nRequested == 0:
            #If no tile needed to be requested, the 'patchAvailable' signal
            #of the render thread will never come.
            #In this case, we need to call the implementation ourselves:
            self._renderScreenshot(s, blowup, filename, patchNumber=0)

    def addLayer(self, a, display='grayscale', opacity=1.0, \
                 name='Unnamed Layer', visible=True, interpretChannelsAs=None):
        print "adding layer '%s', shape=%r, %r" % (name, a.shape, type(a))

        """Adds a new layer on top of the layer stack (such that it will be
        above all currently defined layers). The array 'a' may be a simple
        numpy.ndarray or implicitly defined via a LazyflowArraySource.

        Returns the created Layer object. The layer can either be removed
        by passing this object to self.removeLayer, or by giving a unique
        name.
        """

        if hasattr(a, 'axistags') and not hasattr(a, '_metaParent'):
            #vigra array with axistags
            a = a.withAxes('t', 'x', 'y', 'z', 'c').view(numpy.ndarray)

        if len(a.shape) not in [2,3,5]:
            raise RuntimeError("Cannot interpret array with: shape=%r" \
                               % a.shape)

        volumeImage = True
        if len(a.shape) == 2:
            volumeImage = False
        if len(a.shape) == 3 and a.shape[2] == 3 and interpretChannelsAs == 'RGB':
            volumeImage = False

        Source = ArraySource
        if hasattr(a, '_metaParent'):
            #this is a lazyflow OutputSlot object
            Source = LazyflowSource
            if len(a.shape) == 3:
                print "lazyflow input has shape %r" % (a.shape,)
                o = Op5ifyer(a.operator.graph)
                o.inputs['Input'].connect(a)
                a = o.outputs['Output']
                print "  -> new shape: %r" % (a.shape,)
        elif len(a.shape) != 5 and isinstance(a, numpy.ndarray) and volumeImage:
            a = a[numpy.newaxis, ..., numpy.newaxis]

        elif not isinstance(a, numpy.ndarray): 
            # not a numpy array. Maybe h5py or something else. Embed it.
            if(hasattr(a, 'dtype')):
                a = Array5d(a, dtype=a.dtype)
            else:
                a = Array5d(a, dtype=np.uint8)                

        if volumeImage and (self.editor is None or self.editor.dataShape != a.shape):
            if self.editor:
                print "  new volume layer '%s', shape %r is not compatible with existing shape %r" % (name, a.shape, self.editor.dataShape)
            self.layerstack.clear()
            if isinstance(self.editor, ImageEditor) or self.editor is None:
                self._initVolumeViewing()
            self.editor.dataShape = a.shape
            print "  --> resetting viewer to shape=%r and zero layers" % (self.editor.dataShape,) 
        elif not volumeImage and (self.editor is None or self.editor.dataShape != a.shape[0:2]):
            if self.editor:
                print "  new image layer '%s', shape %r is not compatible with existing shape %r" % (name, a.shape[0:2], self.editor.dataShape)
            self.layerstack.clear()
            if isinstance(self.editor, VolumeEditor) or self.editor is None:
                self._initImageViewing()
            self.editor.dataShape = a.shape[0:2]
            print "  --> resetting viewer to shape=%r and zero layers" % (self.editor.dataShape,) 

        if display == 'grayscale':
            if interpretChannelsAs == None:
                source = Source(a)
                layer = GrayscaleLayer(source)
            elif interpretChannelsAs == "RGB":
                layer = RGBALayer(Source(a[:,:,0]), Source(a[:,:,1]), Source(a[:,:,2]))
        
        elif display == 'randomcolors':
            if a.dtype != numpy.uint8:
                print "layer '%s': implicit conversion from %s to uint8" \
                      % (name, a.dtype)
                if a.dtype == numpy.uint32:
                    a = a.astype(numpy.uint8)
                else:
                    raise RuntimeError("unhandled dtype=%r" % a.dtype)
            source = Source(a)
            layer = ColortableLayer(source, self._randomColors())
        else:
            raise RuntimeError("unhandled type of overlay")
        layer.name = name
        layer.opacity = opacity
        layer.visible = visible
        self.layerstack.append(layer)

        return layer

    def removeLayer(self, layer):
        """Remove layer either by given 'Layer' object
        (as returned by self.addLayer), or by it's name string
        (as given to the name parameter in self.addLayer)"""

        if isinstance(layer, Layer):
            idx = self.layerstack.layerIndex(layer)
            self.layerstack.removeRows(idx, 1)
        else:
            idx = [i for i in range(len(self.layerstack)) if \
                self.layerstack.data(self.layerstack.index(i)).name == layer]
            if len(idx) > 1:
                raise RuntimeError("Trying to remove layer '%s', whose name is"
                    "ambigous as it refers to %d layers" % len(idx))
                return False
            self.layerstack.removeRows(idx[0], 1)
        return True

    @property
    def title(self):
        """Get the window title"""

        return self.windowTitle()

    @title.setter
    def title(self, t):
        """Set the window title"""
        
        self.setWindowTitle(t)

    ### private implementations

    def _initVolumeViewing(self):
        self.layerstack.clear()

        self.editor = VolumeEditor(self.layerstack, labelsink=None)

        if not isinstance(self.viewer, VolumeEditorWidget):
            splitterSizes = self.splitter.sizes()
            self.viewer.setParent(None)
            del self.viewer
            self.viewer = VolumeEditorWidget()
            self.splitter.insertWidget(0, self.viewer)
            self.splitter.setSizes(splitterSizes)
            self.viewer.init(self.editor)

            w = self.viewer
            self.menuView.addAction(w.allZoomToFit)
            self.menuView.addAction(w.allToggleHUD)
            self.menuView.addAction(w.allCenter)
            self.menuView.addSeparator()
            self.menuView.addAction(self.actionCurrentView)
            self.menuView.addAction(w.selectedZoomToFit)
            self.menuView.addAction(w.toggleSelectedHUD)
            self.menuView.addAction(w.selectedCenter)
            self.menuView.addAction(w.selectedZoomToOriginal)
            self.menuView.addAction(w.rubberBandZoom)

            self.editor.newImageView2DFocus.connect(self._setIconToViewMenu)

    def _initImageViewing(self):

        if not isinstance(self.viewer, ImageEditorWidget):
            self.layerstack.clear()
            print "changing to 2D viewer"
            
            w = self.viewer
            if isinstance(w, VolumeEditor):
                self.menuView.removeAction(w.allZoomToFit)
                self.menuView.removeAction(w.allToggleHUD)
                self.menuView.removeAction(w.allCenter)
                self.menuView.removeAction(self.actionCurrentView)
                self.menuView.removeAction(w.selectedZoomToFit)
                self.menuView.removeAction(w.toggleSelectedHUD)
                self.menuView.removeAction(w.selectedCenter)
                self.menuView.removeAction(w.selectedZoomToOriginal)
                self.menuView.removeAction(w.rubberBandZoom)

            #remove 3D viewer
            splitterSizes = self.splitter.sizes()
            self.viewer.setParent(None)
            del self.viewer

            self.viewer = ImageEditorWidget()
            self.editor = ImageEditor(layerStackModel=self.layerstack)
            self.viewer.init(self.editor)
            self.splitter.insertWidget(0, self.viewer)
            self.splitter.setSizes(splitterSizes)

    def _renderScreenshot(self, s, blowup, filename, patchNumber):
        progress = 0
        for patchNumber in range(len(s._tiling)):
            p = s.tileProgress(patchNumber) 
            progress += p
        progress = progress/float(len(s._tiling))
        if progress == 1.0:
            s._renderThread.patchAvailable.disconnect(self._renderScreenshotDisconnect)
            
            img = QImage(int(round((blowup*s.sceneRect().size().width()))),
                         int(round((blowup*s.sceneRect().size().height()))),
                         QImage.Format_ARGB32)
            screenshotPainter = QPainter(img)
            screenshotPainter.setRenderHint(QPainter.Antialiasing, True)
            s.render(screenshotPainter, QRectF(0, 0, img.width()-1, img.height()-1), s.sceneRect())
            print "  saving to '%s'" % filename
            img.save(filename)
            del screenshotPainter
            self.editor.navCtrl.enableNavigation = True

    def _setIconToViewMenu(self):
        focused = self.editor.imageViews[self.editor._lastImageViewFocus]
        self.actionCurrentView.setIcon(\
            QIcon(focused._hud.axisLabel.pixmap()))

    def _randomColors(self, M=256):
        """Generates a pleasing color table with M entries."""

        colors = []
        for i in range(M):
            if i == 0:
                colors.append(QColor(0, 0, 0, 0).rgba())
            else:
                h, s, v = random.random(), random.random(), 1.0
                color = numpy.asarray(colorsys.hsv_to_rgb(h, s, v)) * 255
                qColor = QColor(*color)
                colors.append(qColor.rgba())
        return colors


#******************************************************************************
#* if __name__ == '__main__':                                                 *
#******************************************************************************

if __name__ == '__main__':
    from scipy import lena
    from volumina import _testing
    lenaRGB = vigra.impex.readImage(os.path.split(volumina._testing.__file__)[0]+"/lena.png").view(numpy.ndarray).swapaxes(0,1)

    if haveLazyflow:
        from lazyflow.graph import Operator, OutputSlot, InputSlot

        class OpOnDemand(Operator):
            """This simple operator draws (upon any request)
            a number from [0,255] and returns a uniform array containing
            only the drawn number to satisy the request."""

            name = "OpOnDemand"
            category = "Debug"

            inputSlots = [InputSlot('shape')]
            outputSlots = [OutputSlot("output")]

            def notifyConnectAll(self):
                print "notifyConnectAll"
                oslot = self.outputs['output']
                oslot._shape = self.inputs['shape'].value
                oslot._dtype = numpy.uint8
                oslot._axistags = vigra.defaultAxistags(len(oslot._shape))

            def getOutSlot(self, slot, key, result):
                result[:] = numpy.random.randint(0, 255)

    #make the program quit on Ctrl+C
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    v = Viewer()
    v.show()

    v.addLayer(lena(), name='lena gray')
    v.addLayer(lenaRGB, name='lena RGB', interpretChannelsAs='RGB')

    d = (numpy.random.random((1000, 800, 50)) * 255).astype(numpy.uint8)
    assert d.ndim == 3

    #FIXME: this does not work
    #d = d.view(vigra.VigraArray)

    v.addLayer(d, display='randomcolors', name="numpy 3D", visible=True)
    v.addLayer(d[numpy.newaxis, ..., numpy.newaxis], display='randomcolors', \
               name="numpy 5D", visible=False)

    #test adding and removing layers
    oldLen = len(v.layerstack)
    l = v.addLayer(numpy.zeros((1000,800,50)))
    assert len(v.layerstack) == oldLen+1
    v.removeLayer(l)
    assert len(v.layerstack) == oldLen
    l = v.addLayer(numpy.zeros((1000,800,50)), name="xxx")
    assert len(v.layerstack) == oldLen+1
    v.removeLayer("xxx")
    assert len(v.layerstack) == oldLen

    v.title = 'My Data Example'
    if haveLazyflow:
        g = Graph()
        op = OpOnDemand(g)
        op.inputs['shape'].setValue(d.shape)
        v.addLayer(op.outputs['output'], name='lazyflow 3D', visible=False)
        op2 = OpOnDemand(g)
        op2.inputs['shape'].setValue((1,) + d.shape + (1,))
        v.addLayer(op2.outputs['output'], name='lazyflow 5D', visible=False)

    app.exec_()