ZXing 0.22.0, Apache-2.0. Build offline browser asset from this entry point with @zxing/library@0.22.0 and esbuild@0.25.12:

    esbuild annual-barcode.mjs --bundle --minify --format=iife --global-name=SettaBarcode --legal-comments=inline --outfile=../../assets/zxing-barcode-0.22.0.js
