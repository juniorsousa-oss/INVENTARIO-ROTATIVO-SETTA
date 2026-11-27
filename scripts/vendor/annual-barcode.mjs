import Source from '@zxing/library/esm/core/RGBLuminanceSource.js';
import Bitmap from '@zxing/library/esm/core/BinaryBitmap.js';
import Hybrid from '@zxing/library/esm/core/common/HybridBinarizer.js';
import Hints from '@zxing/library/esm/core/DecodeHintType.js';
import Code128 from '@zxing/library/esm/core/oned/Code128Reader.js';
import Code39 from '@zxing/library/esm/core/oned/Code39Reader.js';
import EAN13 from '@zxing/library/esm/core/oned/EAN13Reader.js';
import EAN8 from '@zxing/library/esm/core/oned/EAN8Reader.js';
const barcodeReaders = [new Code128(), new Code39(), new EAN13(), new EAN8()];
const barcodeHints = new Map([[Hints.TRY_HARDER, true]]);
export function decodeBarcode(frame) {
  const {data, width, height} = frame;
  const gray = new Uint8ClampedArray(width * height);
  for (let i = 0, j = 0; i < gray.length; i++, j += 4) gray[i] = (data[j] + 2 * data[j+1] + data[j+2]) >> 2;
  const bitmap = new Bitmap(new Hybrid(new Source(gray, width, height)));
  for (const reader of barcodeReaders) {
    try { return reader.decode(bitmap, barcodeHints).getText(); } catch (_) { /* try next format */ }
  }
  return null;
}
