"""Independent full-source boundaries, no draft-window anchoring."""
import delivery_v64 as current
import catalogued_boundary_v65 as boundaries

VERSION = 'delivery-v11.65-full-source-catalogue-position-semantic-boundaries-20261010'


def activate():
    current.activate()
    boundaries.bounded=current.current.current.current.current.visible.review
    current.pipeline.final_boundary.review=boundaries.review
    current.pipeline.previous.VERSION=VERSION
    current.pipeline.previous.IMPLEMENTATION_FILES=list(dict.fromkeys(
        current.pipeline.previous.IMPLEMENTATION_FILES+['delivery_v65.py','catalogued_boundary_v65.py']))


if __name__=='__main__':
    activate()
    current.pipeline.previous.main()
