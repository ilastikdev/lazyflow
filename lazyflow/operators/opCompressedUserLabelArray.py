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
# Built-in
import logging
import collections

# Third-party
import numpy

# Lazyflow
from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.roi import TinyVector, getIntersectingBlocks, getBlockBounds, roiToSlice, getIntersection, roiFromShape
from lazyflow.operators.opCache import OpCache
from lazyflow.operators.opCompressedCache import OpCompressedCache
from lazyflow.rtype import SubRegion

logger = logging.getLogger(__name__)

class OpCompressedUserLabelArray(OpCompressedCache):
    """
    A subclass of OpCompressedCache that is suitable for storing user-drawn label pixels.
    Note that setInSlot has special functionality (only non-zero pixels are written, and there is also an "eraser" pixel value).

    See note below about blockshape changes.
    """
    #Input = InputSlot()
    shape = InputSlot(optional=True) # Should not be used.
    eraser = InputSlot()
    deleteLabel = InputSlot(optional = True)
    blockShape = InputSlot() # If the blockshape is changed after labels have been stored, all cache data is lost.

    #Output = OutputSlot()
    #nonzeroValues = OutputSlot()
    #nonzeroCoordinates = OutputSlot()
    nonzeroBlocks = OutputSlot()
    #maxLabel = OutputSlot()
    
    Projection2D = OutputSlot() # A somewhat magic output that returns a projection of all 
                                # label data underneath a given roi, from all slices.
                                # If, for example, a 256x1x256 tile is requested from this slot,
                                # It will return a projection of ALL labels that fall within the 256 x ... x 256 tile.
                                # (The projection axis is *inferred* from the shape of the requested data).
                                # The projection data is float32 between 0.0 and 1.0, where:
                                # - Exactly 0.0 means "no labels under this pixel"
                                # - 1/256.0 means "labels in the first slice"
                                # - ...
                                # - 1.0 means "last slice"
                                # The output is suitable for display in a colortable.
    
    def __init__(self, *args, **kwargs):
        super(OpCompressedUserLabelArray, self).__init__( *args, **kwargs )
        self._blockshape = None
        self._label_to_purge = 0
    
    def setupOutputs(self):
        # Due to a temporary naming clash, pass our subclass blockshape to the superclass
        # TODO: Fix this by renaming the BlockShape slots to be consistent.
        self.BlockShape.setValue( self.blockShape.value )
        
        super( OpCompressedUserLabelArray, self ).setupOutputs()
        if self.Output.meta.NOTREADY:
            self.nonzeroBlocks.meta.NOTREADY = True
            return
        self.nonzeroBlocks.meta.dtype = object
        self.nonzeroBlocks.meta.shape = (1,)
        
        # Overwrite the Output metadata (should be uint8 no matter what the input data is...)
        self.Output.meta.assignFrom(self.Input.meta)
        self.Output.meta.dtype = numpy.uint8
        self.Output.meta.shape = self.Input.meta.shape[:-1] + (1,)
        self.Output.meta.drange = (0,255)
        self.OutputHdf5.meta.assignFrom(self.Output.meta)
        
        # The Projection2D slot is a strange beast:
        # It appears to have the same output shape as any other output slot,
        #  but it can only be accessed in 2D slices.
        self.Projection2D.meta.assignFrom(self.Output.meta)
        self.Projection2D.meta.dtype = numpy.float32
        self.Projection2D.meta.drange = (0.0, 1.0)
        

        # Overwrite the blockshape
        if self._blockshape is None:
            self._blockshape = numpy.minimum( self.BlockShape.value, self.Output.meta.shape )
        elif self.blockShape.value != self._blockshape:
            nonzero_blocks_destination = [None]
            self._execute_nonzeroBlocks(nonzero_blocks_destination)
            nonzero_blocks = nonzero_blocks_destination[0]
            if len(nonzero_blocks) > 0:
                raise RuntimeError( "You are not permitted to reconfigure the labeling operator after you've already stored labels in it." )

        # Overwrite chunkshape now that blockshape has been overwritten
        self._chunkshape = self._chooseChunkshape(self._blockshape)

        self._eraser_magic_value = self.eraser.value
        
        # Are we being told to delete a label?
        if self.deleteLabel.ready():
            new_purge_label = self.deleteLabel.value
            if self._label_to_purge != new_purge_label:
                self._label_to_purge = new_purge_label
                if self._label_to_purge > 0:
                    self._purge_label( self._label_to_purge )
    
    def _purge_label(self, label_to_purge):
        """
        Scan through all labeled pixels.
        (1) Clear all pixels of the given value (set to 0)
        (2) Decrement all labels above that value so the set of stored labels is consecutive
        """
        changed_block_rois = []
        #stored_block_rois = self.CleanBlocks.value
        stored_block_roi_destination = [None]
        self.execute(self.CleanBlocks, (), SubRegion( self.Output, (0,),(1,) ), stored_block_roi_destination)
        stored_block_rois = stored_block_roi_destination[0]

        for block_roi in stored_block_rois:
            # Get data
            block_shape = numpy.subtract( block_roi[1], block_roi[0] )
            block = numpy.ndarray( shape=block_shape, dtype=self.Output.meta.dtype )
            self.execute(self.Output, (), SubRegion( self.Output, *block_roi ), block)

            # Locate pixels to change
            matching_label_coords = numpy.nonzero( block == label_to_purge )
            coords_to_decrement = block > label_to_purge

            # Change the data
            block[matching_label_coords] = 0
            block = numpy.where( coords_to_decrement, block-1, block )
            
            # Update cache with the new data (only if something really changed)
            if len(matching_label_coords[0]) > 0 or len(coords_to_decrement[0]) > 0:
                super( OpCompressedUserLabelArray, self )._setInSlotInput( self.Input, (), SubRegion( self.Output, *block_roi ), block, store_zero_blocks=False )
                changed_block_rois.append( block_roi )

        for block_roi in changed_block_rois:
            # FIXME: Shouldn't this dirty notification be handled in OpCompressedCache?
            self.Output.setDirty( *block_roi )
    
    def execute(self, slot, subindex, roi, destination):
        if slot == self.Output:
            self._executeOutput(roi, destination)
        elif slot == self.nonzeroBlocks:
            self._execute_nonzeroBlocks(destination)
        elif slot == self.Projection2D:
            self._executeProjection2D(roi, destination)
        else:
            return super( OpCompressedUserLabelArray, self ).execute( slot, subindex, roi, destination )

    def _executeOutput(self, roi, destination):
        assert len(roi.stop) == len(self.Input.meta.shape), \
            "roi: {} has the wrong number of dimensions for Input shape: {}"\
            "".format( roi, self.Input.meta.shape )
        assert numpy.less_equal(roi.stop, self.Input.meta.shape).all(), \
            "roi: {} is out-of-bounds for Input shape: {}"\
            "".format( roi, self.Input.meta.shape )
        
        block_starts = getIntersectingBlocks( self._blockshape, (roi.start, roi.stop) )
        self._copyData(roi, destination, block_starts)
        return destination

    def _execute_nonzeroBlocks(self, destination):
        stored_block_rois_destination = [None]
        self._executeCleanBlocks( stored_block_rois_destination )
        stored_block_rois = stored_block_rois_destination[0]
        block_slicings = map( lambda block_roi: roiToSlice(*block_roi), stored_block_rois )
        destination[0] = block_slicings

    def _executeProjection2D(self, roi, destination):
        assert sum(TinyVector(destination.shape) > 1) <= 2, "Projection result must be exactly 2D"
        
        # First, we have to determine which axis we are projecting along.
        # We infer this from the shape of the roi.
        # For example, if the roi is of shape 
        #  zyx = (1,256,256), then we know we're projecting along Z
        # If more than one axis has a width of 1, then we choose an 
        #  axis according to the following priority order: zyxt
        tagged_input_shape = self.Input.meta.getTaggedShape()
        tagged_result_shape = collections.OrderedDict( zip( tagged_input_shape.keys(),
                                                            destination.shape ) )
        nonprojection_axes = []
        for key in tagged_input_shape.keys():
            if (key == 'c' or tagged_input_shape[key] == 1 or tagged_result_shape[key] > 1):
                nonprojection_axes.append( key )
            
        possible_projection_axes = set(tagged_input_shape) - set(nonprojection_axes)
        if len(possible_projection_axes) == 0:
            # If the image is 2D to begin with, 
            #   then the projection is simply the same as the normal output,
            #   EXCEPT it is made binary
            self.Output(roi.start, roi.stop).writeInto(destination).wait()
            
            # make binary
            numpy.greater(destination, 0, out=destination)
            return
        
        for k in 'zyxt':
            if k in possible_projection_axes:
                projection_axis_key = k
                break

        # Now we know which axis we're projecting along.
        # Proceed with the projection, working blockwise to avoid unecessary work in unlabeled blocks
        
        projection_axis_index = self.Input.meta.getAxisKeys().index(projection_axis_key)
        projection_length = tagged_input_shape[projection_axis_key]
        input_roi = roi.copy()
        input_roi.start[projection_axis_index] = 0
        input_roi.stop[projection_axis_index] = projection_length

        destination[:] = 0.0

        # Get the logical blocking.
        block_starts = getIntersectingBlocks( self._blockshape, (input_roi.start, input_roi.stop) )

        # (Parallelism wouldn't help here: h5py will serialize these requests anyway)
        block_starts = map( tuple, block_starts )
        for block_start in block_starts:
            if block_start not in self._cacheFiles:
                # No label data in this block.  Move on.
                continue

            entire_block_roi = getBlockBounds( self.Output.meta.shape, self._blockshape, block_start )

            # This block's portion of the roi
            intersecting_roi = getIntersection( (input_roi.start, input_roi.stop), entire_block_roi )
            
            # Compute slicing within the deep array and slicing within this block
            deep_relative_intersection = numpy.subtract(intersecting_roi, input_roi.start)
            block_relative_intersection = numpy.subtract(intersecting_roi, block_start)
                        
            deep_data = self._getBlockDataset( entire_block_roi )[roiToSlice(*block_relative_intersection)]

            # make binary and convert to float
            deep_data_float = numpy.where( deep_data, numpy.float32(1.0), numpy.float32(0.0) )
            
            # multiply by slice-index
            deep_data_view = numpy.rollaxis(deep_data_float, projection_axis_index, 0)

            min_deep_slice_index = deep_relative_intersection[0][projection_axis_index]
            max_deep_slice_index = deep_relative_intersection[1][projection_axis_index]
            
            def calc_color_value(slice_index):
                # Note 1: We assume that the colortable has at least 256 entries in it,
                #           so, we try to ensure that all colors are above 1/256 
                #           (we don't want colors in low slices to be rounded to 0)
                # Note 2: Ideally, we'd use a min projection in the code below, so that 
                #           labels in the "back" slices would appear occluded.  But the 
                #           min projection would favor 0.0.  Instead, we invert the 
                #           relationship between color and slice index, do a max projection, 
                #           and then re-invert the colors after everything is done.
                #           Hence, this function starts with (1.0 - ...)
                return (1.0 - (float(slice_index) / projection_length)) * (1.0 - 1.0/255) + 1.0/255.0
            min_color_value = calc_color_value(min_deep_slice_index)
            max_color_value = calc_color_value(max_deep_slice_index)
            
            num_slices = max_deep_slice_index - min_deep_slice_index
            deep_data_view *= numpy.linspace( min_color_value, max_color_value, num=num_slices )\
                              [ (slice(None),) + (None,)*(deep_data_view.ndim-1) ]

            # Take the max projection of this block's data.
            block_max_projection = numpy.amax(deep_data_float, axis=projection_axis_index, keepdims=True)

            # Merge this block's projection into the overall projection.
            destination_relative_intersection = numpy.array(deep_relative_intersection)
            destination_relative_intersection[:, projection_axis_index] = (0,1)            
            destination_subview = destination[roiToSlice(*destination_relative_intersection)]            
            numpy.maximum(block_max_projection, destination_subview, out=destination_subview)
            
            # Invert the nonzero pixels so increasing colors correspond to increasing slices.
            # See comment in calc_color_value(), above.
            destination_subview[:] = numpy.where(destination_subview, 
                                                 numpy.float32(1.0) - destination_subview, 
                                                 numpy.float32(0.0))
        return

    def _copyData(self, roi, destination, block_starts):
        """
        Copy data from each block into the destination array.
        For blocks that aren't currently stored, just write zeros.
        """
        # (Parallelism not needed here: h5py will serialize these requests anyway)
        block_starts = map( tuple, block_starts )
        for block_start in block_starts:
            entire_block_roi = getBlockBounds( self.Output.meta.shape, self._blockshape, block_start )

            # This block's portion of the roi
            intersecting_roi = getIntersection( (roi.start, roi.stop), entire_block_roi )
            
            # Compute slicing within destination array and slicing within this block
            destination_relative_intersection = numpy.subtract(intersecting_roi, roi.start)
            block_relative_intersection = numpy.subtract(intersecting_roi, block_start)
            
            if block_start in self._cacheFiles:
                # Copy from block to destination
                dataset = self._getBlockDataset( entire_block_roi )
                destination[ roiToSlice(*destination_relative_intersection) ] = dataset[ roiToSlice( *block_relative_intersection ) ]
            else:
                # Not stored yet.  Overwrite with zeros.
                destination[ roiToSlice(*destination_relative_intersection) ] = 0

    def propagateDirty(self, slot, subindex, roi):
        # There should be no way to make the output dirty except via setInSlot()
        pass

    def setInSlot(self, slot, subindex, roi, new_pixels):
        if slot == self.Input:
            self._setInSlotInput(slot, subindex, roi, new_pixels)
        else:
            # We don't yet support the InputHdf5 slot in this function.
            assert False, "Unsupported slot for setInSlot: {}".format( slot.name )
            
    def _setInSlotInput(self, slot, subindex, roi, new_pixels):
        """
        Since this is a label array, inserting pixels has a special meaning:
        We only overwrite the new non-zero pixels. In the new data, zeros mean "don't change".
        
        So, here's what each pixel we're adding means:
        0: don't change
        1: change to 1
        2: change to 2
        ...
        N: change to N
        magic_eraser_value: change to 0  
        """

        # Extract the data to modify
        original_data = numpy.ndarray( shape=new_pixels.shape, dtype=self.Output.meta.dtype )
        self.execute(self.Output, (), roi, original_data)
        
        # Reset the pixels we need to change (so we can use |= below)
        original_data[new_pixels.nonzero()] = 0
        
        # Update
        original_data |= new_pixels

        # Replace 'eraser' values with zeros.
        cleaned_data = numpy.where(original_data == self._eraser_magic_value, 0, original_data[:])

        # Set in the cache (our superclass).
        super( OpCompressedUserLabelArray, self )._setInSlotInput( slot, subindex, roi, cleaned_data, store_zero_blocks=False )
        
        # FIXME: Shouldn't this notification be triggered from within OpCompressedCache?
        self.Output.setDirty( roi.start, roi.stop )
        
        return cleaned_data # Internal use: Return the cleaned_data        

    def ingestData(self, slot):
        """
        Read the data from the given slot and copy it into this cache.
        The rules about special pixel meanings apply here, just like setInSlot
        
        Returns: the max label found in the slot.
        """
        assert self._blockshape is not None
        assert self.Input.meta.shape == slot.meta.shape
        max_label = 0

        # Get logical blocking.
        block_starts = getIntersectingBlocks( self._blockshape, roiFromShape(self.Input.meta.shape) )
        block_starts = map( tuple, block_starts )

        # Write each block
        for block_start in block_starts:
            block_roi = getBlockBounds( self.Input.meta.shape, self._blockshape, block_start )
            
            # Request the block data
            block_data = slot(*block_roi).wait()
            
            # Write into the array
            subregion_roi = SubRegion(self.Input, *block_roi)
            cleaned_block_data = self._setInSlotInput( self.Input, (), subregion_roi, block_data )
            
            max_label = max( max_label, cleaned_block_data.max() )
        
        return max_label
            
            


