"""Accept a literal focus opening as well as null, without moving its boundary."""
import delivery_v73 as current

VERSION = 'delivery-v11.74-literal-focus-opening-aligned-object-review-20261010'
pipeline = current.pipeline


def proposal(text, raw):
    units = []
    for i, piece in enumerate(raw['pieces']):
        quote = piece['start_anchor']
        if quote is None:
            if i != 0:
                return None, ['只有范围首片可以用空起点']
            quote = text[:30]
        units.append({'start_quote': quote,
            'start_occurrence': 1 if i == 0 else piece['start_occurrence'],
            'object': piece['physical_object'], 'theme': piece['physical_object'],
            'why': piece['why'], 'confidence': piece['confidence'],
            'uncertainties': piece['uncertainties']})
    # Literal first anchors are still validated at offset0 by the common builder.
    # No truncation/rewriting of model output and no silent skipping of the intro.
    return {'units': units}, []


def activate():
    current.activate()
    current.current.objects.proposal = proposal
    pipeline.previous.VERSION = VERSION
    pipeline.previous.IMPLEMENTATION_FILES = list(dict.fromkeys(
        pipeline.previous.IMPLEMENTATION_FILES + ['delivery_v74.py']))


if __name__ == '__main__':
    activate()
    pipeline.previous.main()
