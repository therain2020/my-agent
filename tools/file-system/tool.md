---
name: file-system
version: "1.0.0"
description: 文件系统读写操作
objects: [file, directory]
capabilities:
  - name: read_file
    description: 读取文件内容
    parameters:
      path: { type: string, required: true, description: "文件路径" }
      encoding: { type: string, default: "utf-8" }
    returns: { type: string, description: "文件内容" }
    side_effects: [reads filesystem]
    timeout_ms: 5000
  - name: write_file
    description: 写入文件内容
    parameters:
      path: { type: string, required: true }
      content: { type: string, required: true }
    returns: { type: boolean }
    side_effects: [modifies filesystem]
    timeout_ms: 10000
entry_points:
  read_file: read.py:read_file
  write_file: write.py:write_file
runtime: import
source: builtin
---

# file-system 工具

提供文件系统的读写能力。所有路径均为相对于项目根目录的路径。

## 使用方法

### 读取文件
调用 read_file，传入文件路径。返回文件内容。

### 写入文件
调用 write_file，传入文件路径和内容。返回是否成功。
