import os

file_path = '/opt/wecom-callback/src/crewai_enterprise/utils/file_extractor.py'
if not os.path.exists(file_path):
    print(f'File not found: {file_path}')
    exit(1)

content = open(file_path).read()
old = '        from paddleocr import PaddleOCR'
new = '        from paddleocr import PaddleOCR\n        if os.getenv("DISABLE_OCR") == "true": return None'

if 'DISABLE_OCR' in content:
    print('Already patched')
    exit(0)

if old in content:
    with open(file_path, 'w') as f:
        f.write(content.replace(old, new, 1))
    print('Patched successfully')
else:
    print('Anchor text not found')
