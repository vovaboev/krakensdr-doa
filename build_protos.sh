#! /bin/bash
python3 -m grpc_tools.protoc -Iproto --python_out=backend --grpc_python_out=backend proto/adder.proto
python3 -m grpc_tools.protoc -Iproto --python_out=backend --grpc_python_out=backend proto/kraken.proto