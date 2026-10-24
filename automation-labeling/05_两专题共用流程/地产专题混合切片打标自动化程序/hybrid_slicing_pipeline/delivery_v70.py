"""Full-source semantic boundary decisions with global literal anchors."""
import delivery_v69 as current
import full_source_boundary_v70 as boundaries

VERSION = 'delivery-v11.70-full-source-global-literal-object-boundaries-20261010'
pipeline = current.pipeline


def activate():
    current.activate()
    pipeline.final_boundary.review = boundaries.review
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v70.py', 'full_source_boundary_v70.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
