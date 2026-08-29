"""PyInstaller hook：onnxruntime 动态加载的 DLL 需手动收集。"""
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = collect_all('onnxruntime')
binaries += collect_dynamic_libs('onnxruntime')
