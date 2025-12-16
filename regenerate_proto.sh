#!/bin/bash
# Скрипт для регенерации protobuf файлов на сервере с правильными зависимостями

set -e

echo "=== Регенерация protobuf файлов ==="

# Установка grpcio-tools совместимой с protobuf 4.25.2
pip install "grpcio-tools>=1.62,<1.70" --no-cache-dir

# Генерация файлов для grpcio
python -m grpc_tools.protoc \
  -I. \
  --python_out=. \
  --grpc_python_out=. \
  --pyi_out=. \
  app/marznode/marznode.proto

# Генерация файлов для grpclib
python -m grpc_tools.protoc \
  -I. \
  --python_out=. \
  --grpclib_python_out=. \
  app/marznode/marznode.proto

echo "✓ Protobuf файлы успешно сгенерированы"
echo ""
echo "Сгенерированные файлы:"
ls -lh app/marznode/marznode_pb2.py
ls -lh app/marznode/marznode_pb2_grpc.py
ls -lh app/marznode/marznode_grpc.py
ls -lh app/marznode/marznode_pb2.pyi

