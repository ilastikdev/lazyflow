import numpy, vigra
import time
from lazyflow.graph import *
import gc
from lazyflow import roi
import threading

from lazyflow.operators.operators import OpArrayCache, OpArrayPiper, OpMultiArrayPiper, OpMultiMultiArrayPiper
from lazyflow.operators.obsoleteOperators import OpArrayBlockCache, OpArraySliceCache, OpArraySliceCacheBounding

__testing__ = False

from tests.mockOperators import OpA, OpB, OpC


class OperatorGroupA(OperatorGroup):
    name="OperatorGroupA"
    
    inputSlots = [InputSlot("Input")]
    outputSlots = [MultiOutputSlot("MultiOutput")]
    
    def createInnerOperators(self):
        # this method must setup the
        # inner operators and connect them (internally)
        
        self.source0 = OpArrayPiper(self.graph)
        self.source0.inputs["Input"].connect(self.inputs["Input"].partner)
        opa1 = OpA(self.graph)
        opa2 = OpB(self.graph)
        
        opb = OpMultiArrayPiper(self.graph)
        opc = OpB(self.graph)
        opd = OpArrayCache(self.graph)
        self.ope = OpMultiArrayPiper(self.graph)
        
        opa1.inputs["Input"].connect(source0.outputs["Output"])
        opa2.inputs["Input"].connect(source0.outputs["Output"])

        opb.inputs["MultiInput"].connectAdd(opa1.outputs["Output"])
        opb.inputs["MultiInput"].connectAdd(opa2.outputs["Output"])
        
        opc.inputs["Input"].connect(opb.outputs["MultiOutput"])
        opd.inputs["Input"].connect(opc.outputs["Output"])
        self.ope.inputs["MultiInput"].connect(opd.outputs["Output"])        
        
    def setupInputSlots(self):
        # this method must return a hash that
        # contains the inner slots corresponding
        # to the slotname
        inputs = {}
        inputs["Input"] = self.source0.inputs["Input"]
        self._visibleInputs = inputs


    
    def setupOutputSlots(self):
        self._visibleOutputs = {}
        self._visibleOutputs["MultiOutput"] = self.ope.outputs["MultiOutput"]



Operators.registerOperatorSubclasses()

g = Graph(numThreads = 2)

source0 = OpArrayPiper(g)
source0.inputs["Input"].setValue(numpy.zeros(shape = (200,100), dtype=numpy.uint8))

opa1 = OpA(g)
opa2 = OpB(g)

opb = OpMultiArrayPiper(g)
opc = OpB(g)
opd = OpArrayCache(g)
ope = OpMultiArrayPiper(g)


opa1.inputs["Input"].connect(source0.outputs["Output"])
opa2.inputs["Input"].connect(source0.outputs["Output"])

opb.inputs["MultiInput"].connectAdd(opa1.outputs["Output"])
opb.inputs["MultiInput"].connectAdd(opa2.outputs["Output"])

opc.inputs["Input"].connect(opb.outputs["MultiOutput"])
opd.inputs["Input"].connect(opc.outputs["Output"])
print "#############"
print len(opd.outputs["Output"])
print "#############"
ope.inputs["MultiInput"].connect(opd.outputs["Output"])


opGA = OperatorGroupA(g)

print len(opd.outputs["Output"])
print len(ope.inputs["MultiInput"])
print len(ope.outputs["MultiOutput"])


opGA.inputs["Input"].connect(source0.outputs["Output"])

print opGA.outputs["MultiOutput"], len(opGA.outputs["MultiOutput"])
print opGA.ope.outputs["MultiOutput"], len(opGA.ope.outputs["MultiOutput"])

res1 = opd.outputs["Output"][0][:].allocate().wait()

res2 = opGA.outputs["MultiOutput"][0][:].allocate().wait()


print g.saveSubGraph({},{"Out": opGA.outputs["MultiOutput"]})

g.finalize()