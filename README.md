# 文件完整性檢查器 (CRC32)

一個跨平台（Linux/macOS/Windows）的 Python 腳本，用於使用 CRC32 校驗值來生成和驗證整個目錄樹的文件與目錄完整性。適合檢測意外損壞、誤刪、誤改等情況。當文件數量達到數十萬乃至百萬級時，也能透過以下優化措施獲得較佳效能。

## 目錄

- [主要功能](#主要功能)
- [環境要求](#環境要求)
- [安裝與準備](#安裝與準備)
- [使用方法](#使用方法)
  - [生成 Baseline](#生成-baseline)
  - [對比校驗](#對比校驗)
- [日誌格式說明](#日誌格式說明)
- [輸出示例](#輸出示例)
- [示例工作流程](#示例工作流程)
- [大規模文件集的效能注意事項與優化建議](#大規模文件集的效能注意事項與優化建議)
- [許可協議](#許可協議)

---

## 主要功能

- **CRC32 校驗**  
  採用 Python 標準庫 `zlib.crc32` 計算每個文件的 CRC32 校驗值，速度極快，適合檢測意外損壞或同步差異（不適用於抵抗惡意碰撞）。

- **目錄/文件元數據記錄**  
  - Linux/macOS：記錄每個目錄的相對路徑、UID、GID 和 POSIX 權限（mode）；記錄每個文件的 CRC32、大小、UID、GID、mode。  
  - Windows：由於不使用 POSIX 權限，UID/GID/mode 欄位均寫為 0 0 000，但仍記錄相對路徑與文件大小，以便驗證一致性。

- **並行處理**  
  使用 `ThreadPoolExecutor` 在多個線程中並發計算 CRC32，並以 1 MiB 塊大小一次性讀取以減少系統呼叫開銷。線程數可配置（預設為 4）。

- **純文本輸出**  
  不帶任何 ANSI 顏色碼，所有結果以純文本形式輸出，便於重定向到文件或日誌系統。包括缺失/額外目錄與文件、CRC32/大小/UID/GID/權限不匹配，以及無法讀取文件等資訊。

---

## 環境要求

- Python 3.7+
- 僅依賴標準庫：`os`、`stat`、`zlib`、`argparse`、`pathlib`、`concurrent.futures`、`time`
- Linux/macOS/Windows

---

## 安裝與準備

```bash
git clone https://github.com/yourusername/file-integrity-crc32.git
cd file-integrity-crc32
# 使腳本可執行（僅 Linux/macOS）
chmod +x file_integrity.py
# 確認 Python 版本
python3 --version
```

（可選）測試數據產生腳本：可使用 `generate_test_files.py` 快速生成大量測試文件。

---

## 使用方法

### 生成 Baseline

掃描指定目錄下所有目錄與文件，將其元數據與 CRC32 寫入基線日誌，預設文件名為 `.integrity_crc32.log`。

#### Linux/macOS

```bash
./file_integrity.py baseline \
  --path /path/to/your_data \
  --threads 4 \
  --log /path/to/your_data/.integrity_crc32.log
```

#### Windows

```powershell
python file_integrity.py baseline `
  --path "Z:\your_data" `
  --threads 4 `
  --log "Z:\your_data\.integrity_crc32.log"
```

### 參數說明

- `--path`：要掃描的根目錄
- `--threads <N>`：並行執行計算 CRC32 的線程數（預設 4）
- `--log <filepath>`：輸出基線日誌的路徑，若不指定，預設為 `<path>/.integrity_crc32.log`

---

### 對比校驗

將當前目錄樹與先前生成的基線日誌比較，輸出所有差異。

#### Linux/macOS

```bash
./file_integrity.py verify \
  --path /path/to/your_data \
  --threads 4 \
  --log /path/to/your_data/.integrity_crc32.log \
  --check-idmap \
  --check-root
```

#### Windows

```powershell
python file_integrity.py verify `
  --path "Z:\your_data" `
  --threads 4 `
  --log "Z:\your_data\.integrity_crc32.log" `
  --check-idmap `
  --check-root
```

- `--check-idmap`：僅 Linux/macOS，檢查 UID/GID = 65534（nobody/nogroup）
- `--check-root`：僅 Linux/macOS，檢查 UID/GID = 0（root）

---

## 日誌格式說明

每行為以下之一：

```
DIR   <rel_path>   <uid>   <gid>   <mode>
FILE  <crc32>      <rel_path>   <size>   <uid>   <gid>   <mode>
```

- `<rel_path>`：相對於 `--path` 的子目錄路徑，使用「/」分隔
- `<uid>`、`<gid>`、`<mode>`：Linux/macOS 實際值，Windows 為 0 0 000
- `<crc32>`：8 位十六進制 CRC32 校驗值（小寫）
- `<size>`：文件大小（Byte）

---

## 輸出示例

```text
--- Summary ---
Start time         : 2025-06-01 15:00:00
Elapsed time       :  5.23 seconds
Dirs baseline      : 1000
Dirs current       : 1001
Files baseline     : 10000
Files current      : 10002
----------------

Missing directories (in baseline but not on disk):
  - subdir_045

Extra directories (on disk but not in baseline):
  + extra_dir_new

Missing files (in baseline but not on disk):
  - subdir_010/file_00010.dat

Extra files (on disk but not in baseline):
  + subdir_020/extra_file_123.dat

Files with CRC32 mismatches:
  ✗ subdir_020/file_00020.dat

Files with Size mismatches:
  ✗ subdir_020/file_00020.dat

Files with UID mismatches:
  ✗ subdir_030/file_00030.dat

Files with GID mismatches:
  ✗ subdir_040/file_00040.dat

Files with Mode mismatches:
  ✗ subdir_050/file_00050.dat

Files flagged for ID mapping issues (UID/GID=65534):
  ! subdir_060/file_00060.dat

Files flagged for Root squash issues (UID/GID=0):
  ! subdir_070/file_00070.dat

Files with errors (could not read):
  ! subdir_080/file_00080.dat
----------------
```

---

## 示例工作流程

1. 生成 Baseline

    ```bash
    ./file_integrity.py baseline \
      --path /mnt/nfs_shared/test_data \
      --threads 4 \
      --log /mnt/nfs_shared/test_data/.integrity_crc32.log
    ```

2. （可選）手動或使用腳本注入異常

    ```bash
    rm -rf /mnt/nfs_shared/test_data/subdir_045
    rm /mnt/nfs_shared/test_data/subdir_010/file_000010.dat
    echo "extra" > /mnt/nfs_shared/test_data/subdir_020/extra_file.dat
    echo "append" >> /mnt/nfs_shared/test_data/subdir_020/file_000020.dat
    chmod 000 /mnt/nfs_shared/test_data/subdir_080/file_000080.dat
    ```

3. 執行校驗

    ```bash
    ./file_integrity.py verify \
      --path /mnt/nfs_shared/test_data \
      --threads 4 \
      --log /mnt/nfs_shared/test_data/.integrity_crc32.log \
      --check-idmap \
      --check-root
    ```

---

## 大規模文件集的效能注意事項與優化建議

1. **流式遍歷**  
   使用 `os.scandir()` 或 `os.walk()` 進行流式遍歷，避免一次性收集全部路徑佔用大量記憶體。

    ```python
    import os

    def iter_files(root):
        for entry in os.scandir(root):
            if entry.is_dir(follow_symlinks=False):
                yield from iter_files(entry.path)
            elif entry.is_file(follow_symlinks=False):
                yield entry
    ```

2. **適度並行讀取與計算 CRC32**  
   SSD/NVMe 可用 8–16 線程，HDD 建議 2–4 線程。

    ```python
    from concurrent.futures import ThreadPoolExecutor

    def walk_and_submit(root, executor, root_str, log_handle):
        for entry in os.scandir(root):
            if entry.is_file(follow_symlinks=False):
                executor.submit(process_file, entry, root_str, log_handle)
            elif entry.is_dir(follow_symlinks=False):
                st = entry.stat(follow_symlinks=False)
                rel_dir = os.path.relpath(entry.path, root_str).replace(os.sep, "/")
                mode = stat.filemode(st.st_mode)
                log_handle.write(f"DIR   {rel_dir}  {st.st_uid}  {st.st_gid}  {mode}\n")
                walk_and_submit(entry.path, executor, root_str, log_handle)
    ```

3. **增大讀取緩衝區 (Buffer Size)**

    ```python
    BUF_SIZE = 1 << 20  # 1 MiB
    with open(path, "rb") as f:
        chunk = f.read(BUF_SIZE)
        while chunk:
            crc = zlib.crc32(chunk, crc)
            chunk = f.read(BUF_SIZE)
    ```

4. **直接寫入日誌，避免累積中間結果**

    ```python
    with open(baseline_log, "w", encoding="utf-8") as log_handle, \
         ThreadPoolExecutor(max_workers=threads) as executor:

        def submit_file(entry):
            process_file(entry, root_str, log_handle)

        walk_and_submit(root, executor, root_str, log_handle)
        executor.shutdown(wait=True)
    ```

5. **增量式校驗 (Incremental)**  
   只對新增/已修改/已刪除文件進行 CRC32 重新計算，建議用 SQLite。

---

## 許可協議

MIT License

