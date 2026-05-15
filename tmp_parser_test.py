import re

text = 'johnson bought 50 bags of rice at 5000'

match = re.search(
    r'(?P<quantity>\d+)\s+(?P<unit>\w+)\s+(?:of\s+)?(?P<product>[a-z ]+?)\s+at\s+(?P<unit_price>\d+)',
    text.lower().replace(',', '')
)

if not match:
    raise SystemExit('No match')

result = {
    'quantity': int(match.group('quantity')),
    'unit': match.group('unit'),
    'product': match.group('product').strip(),
    'unit_price': int(match.group('unit_price')),
    'total': int(match.group('quantity')) * int(match.group('unit_price'))
}

print(result)
