import os
import sys

# Force enable OCR for this script
os.environ['DISABLE_OCR'] = 'false'
# Limit threading to save memory/CPU
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

try:
    print("Importing PaddleOCR...")
    from paddleocr import PaddleOCR
    print("Initializing PaddleOCR instance...")
    ocr = PaddleOCR(use_textline_orientation=True, lang="ch", device="cpu")
    print("Initialization successful.")
    
    # Try a dummy OCR if successful
    import numpy as np
    from PIL import Image
    # Create a 100x100 white image
    img = Image.new('RGB', (100, 100), color = (255, 255, 255))
    img_array = np.array(img)
    print("Running dummy OCR...")
    result = ocr.ocr(img_array)
    print(f"OCR result: {result}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
