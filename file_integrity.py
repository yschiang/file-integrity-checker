#!/usr/bin/env python3
import os
import zlib
import stat
import hashlib
import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

HASH_LOG_NAME = ".integrity_hash.log"

def crc32_of_file(file_path):
    """
    回傳檔案的 CRC32 (十六進位字串)，速度非常快，但不具抗碰撞能力。
    """
    buf_size = 1 << 20  # 一次讀 1 MiB 比較快
    crc = 0
    with open(file_path, "rb") as f:
        while True:
            data = f.read(buf_size)
            if not data:
                break
            crc = zlib.crc32(data, crc)
    # zlib.crc32 會輸出一個帶符號的 32-bit int；強制轉成 unsigned
    crc = crc & 0xFFFFFFFF
    return f"{crc:08x}"  # 8 個十六進位字元，左補零


# === 單檔處理：Linux 模式計算 hash + metadata ===
def process_file_linux(file_path):
    try:
        st = file_path.stat()
        size = st.st_size
        uid = st.st_uid
        gid = st.st_gid
        mode = stat.filemode(st.st_mode)

        hash_val = crc32_of_file(file_path)

        return {
            "path": file_path,
            "hash": hash_val,
            "size": size,
            "uid": uid,
            "gid": gid,
            "mode": mode,
            "error": None
        }
    except Exception as e:
        return {
            "path": file_path,
            "hash": None,
            "size": None,
            "uid": None,
            "gid": None,
            "mode": None,
            "error": str(e)
        }

# === 單檔處理：Windows 模式只計算 hash + size，並轉正斜線路徑 ===
def process_file_windows(file_path, base_path):
    try:
        st = file_path.stat()
        size = st.st_size
        hash_val = crc32_of_file(file_path)

        rel = file_path.relative_to(base_path).as_posix()
        return {
            "path": file_path,
            "rel_path": rel,
            "hash": hash_val,
            "size": size,
            "error": None
        }
    except Exception as e:
        rel = file_path.relative_to(base_path).as_posix()
        return {
            "path": file_path,
            "rel_path": rel,
            "hash": None,
            "size": None,
            "error": str(e)
        }

# === 取得所有 regular files ===
def get_all_files(base_path):
    files = set()
    for p in base_path.rglob("*"):
        if p.is_file():
            files.add(p)
    for p in base_path.rglob(".*"):
        if p.is_file():
            files.add(p)
    return list(files)

# === 取得所有 directories ===
def get_all_dirs(base_path):
    dirs = set()
    for p in base_path.rglob("*"):
        if p.is_dir():
            dirs.add(p)
    for p in base_path.rglob(".*"):
        if p.is_dir():
            dirs.add(p)
    return list(dirs)

# === baseline 建立（兼容 Linux/Windows 模式），加上時間與統計，包含目錄與檔案 ===
def generate_baseline(base_path, output_file, threads, is_windows):
    start_time = time.time()
    dirs = get_all_dirs(base_path)
    files = get_all_files(base_path)
    total_dirs = len(dirs)
    total_files = len(files)
    print(f"🔍 Generating baseline for {total_dirs} dirs and {total_files} files using {threads} threads (windows={is_windows})...")

    error_count = 0
    with ThreadPoolExecutor(max_workers=threads) as executor, open(output_file, "w", encoding="utf-8") as log:
        # 先處理所有目錄
        for d in dirs:
            try:
                st = d.stat()
                uid = st.st_uid
                gid = st.st_gid
                mode = stat.filemode(st.st_mode)
                rel = d.relative_to(base_path).as_posix()
                log.write(f"DIR  {rel}  {uid}  {gid}  {mode}\n")
            except Exception as e:
                rel = d.relative_to(base_path).as_posix()
                print(f"❌ {rel} (dir): {e}")
                error_count += 1

        # 再處理所有檔案
        futures = []
        for f in files:
            if is_windows:
                futures.append(executor.submit(process_file_windows, f, base_path))
            else:
                futures.append(executor.submit(process_file_linux, f))

        for future in as_completed(futures):
            result = future.result()
            if is_windows:
                rel = result["rel_path"]
                if result["error"]:
                    print(f"❌ {rel}: {result['error']}")
                    error_count += 1
                else:
                    log.write(f"FILE  {result['hash']}  {rel}  {result['size']}\n")
            else:
                rel = result["path"].relative_to(base_path).as_posix()
                if result["error"]:
                    print(f"❌ {rel}: {result['error']}")
                    error_count += 1
                else:
                    log.write(f"FILE  {result['hash']}  {rel}  {result['size']}  {result['uid']}  {result['gid']}  {result['mode']}\n")

    elapsed = time.time() - start_time
    print(f"✅ Baseline written to {output_file}")
    print(f"--- Summary ---")
    print(f"Start time : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
    print(f"Elapsed    : {elapsed:.2f} seconds")
    print(f"Total dirs : {total_dirs}")
    print(f"Total files: {total_files}")
    print(f"Errors     : {error_count}")
    print(f"----------------")

# === verify 完整性與 metadata（兼容 Linux/Windows baseline 結構），加上時間與檔案與目錄級別報告 ===
def verify_integrity(base_path, input_file, threads, check_idmap, check_root, is_windows):
    start_time = time.time()
    print(f"🔍 Verifying integrity for dirs and files with {threads} threads (windows={is_windows})...")
    baseline_dirs = set()
    baseline_files = {}
    to_check_files = []

    # 讀取 baseline
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            tokens = line.rstrip("\n").split("  ")
            if tokens[0] == "DIR":
                # 格式: DIR  <rel_path>  <uid>  <gid>  <mode>
                if len(tokens) != 5:
                    print(f"⚠️ Skipping invalid dir line: {line.strip()}")
                    continue
                _, rel_path, expected_uid, expected_gid, expected_mode = tokens
                baseline_dirs.add(rel_path)
            elif tokens[0] == "FILE":
                # Windows baseline: FILE  <hash>  <rel_path>  <size>
                # Linux baseline:   FILE  <hash>  <rel_path>  <size>  <uid>  <gid>  <mode>
                if is_windows:
                    if len(tokens) != 4:
                        print(f"⚠️ Skipping invalid file line: {line.strip()}")
                        continue
                    _, expected_hash, rel_path, expected_size = tokens
                    baseline_files[rel_path] = {
                        "expected_hash": expected_hash,
                        "expected_size": int(expected_size)
                    }
                    to_check_files.append({
                        "expected_hash": expected_hash,
                        "expected_size": int(expected_size),
                        "rel_path": rel_path,
                        "path": base_path / Path(rel_path)
                    })
                else:
                    if len(tokens) != 7:
                        print(f"⚠️ Skipping invalid file line: {line.strip()}")
                        continue
                    _, expected_hash, rel_path, expected_size, expected_uid, expected_gid, expected_mode = tokens
                    baseline_files[rel_path] = {
                        "expected_hash": expected_hash,
                        "expected_size": int(expected_size),
                        "expected_uid": int(expected_uid),
                        "expected_gid": int(expected_gid),
                        "expected_mode": expected_mode
                    }
                    to_check_files.append({
                        "expected_hash": expected_hash,
                        "expected_size": int(expected_size),
                        "expected_uid": int(expected_uid),
                        "expected_gid": int(expected_gid),
                        "expected_mode": expected_mode,
                        "rel_path": rel_path,
                        "path": base_path / Path(rel_path)
                    })
            else:
                print(f"⚠️ Skipping invalid line: {line.strip()}")

    # —— 遍歷當前目錄，收集所有實際存在的 rel_path
    current_dirs = set()
    for d in get_all_dirs(base_path):
        current_dirs.add(d.relative_to(base_path).as_posix())
    current_files = set()
    for p in get_all_files(base_path):
        current_files.add(p.relative_to(base_path).as_posix())

    # 統計
    total_dirs_baseline = len(baseline_dirs)
    total_files_baseline = len(baseline_files)
    total_dirs_current = len(current_dirs)
    total_files_current = len(current_files)

    # 初始化計數與記錄
    dir_missing = []
    dir_extra = []
    dir_meta_mismatch = []

    file_missing = []
    file_extra = []
    file_error = []
    file_hash_mismatch = []
    file_size_mismatch = []
    file_uid_mismatch = []
    file_gid_mismatch = []
    file_mode_mismatch = []
    file_idmap_issues = []
    file_root_issues = []

    # 先比對目錄存在與 metadata
    for rel in baseline_dirs:
        if rel not in current_dirs:
            dir_missing.append(rel)
        else:
            # 如果存在且需要校驗 metadata (Linux 模式下)
            if not is_windows:
                try:
                    dpath = base_path / Path(rel)
                    st = dpath.stat()
                    uid = st.st_uid
                    gid = st.st_gid
                    mode = stat.filemode(st.st_mode)
                    # 這裡可以比對預期的 UID/GID/Mode，如有不一致可加入 dir_meta_mismatch
                    # 例如：
                    # if uid != expected_uid or gid != expected_gid or mode != expected_mode:
                    #    dir_meta_mismatch.append(rel)
                    # 為簡化，此處僅讀取 stat，若需要可自行擴充
                except Exception as e:
                    dir_meta_mismatch.append((rel, str(e)))

    for rel in current_dirs:
        if rel not in baseline_dirs:
            dir_extra.append(rel)

    # 再比對檔案
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {}
        for entry in to_check_files:
            if is_windows:
                futures[executor.submit(process_file_windows, entry["path"], base_path)] = entry
            else:
                futures[executor.submit(process_file_linux, entry["path"])] = entry

        for future in as_completed(futures):
            result = future.result()
            entry = futures[future]
            rel = entry["rel_path"]

            if result["error"]:
                file_error.append(rel)
                continue

            if is_windows:
                # Windows 模式：只比對 hash + size
                if result["hash"] != entry["expected_hash"]:
                    file_hash_mismatch.append(rel)
                if result["size"] != entry["expected_size"]:
                    file_size_mismatch.append(rel)
            else:
                # Linux 模式：比對 hash + metadata
                if result["hash"] != entry["expected_hash"]:
                    file_hash_mismatch.append(rel)
                if result["size"] != entry["expected_size"]:
                    file_size_mismatch.append(rel)
                if result["uid"] != entry["expected_uid"]:
                    file_uid_mismatch.append(rel)
                if result["gid"] != entry["expected_gid"]:
                    file_gid_mismatch.append(rel)
                if result["mode"] != entry["expected_mode"]:
                    file_mode_mismatch.append(rel)
                if check_idmap and (result["uid"] == 65534 or result["gid"] == 65534):
                    file_idmap_issues.append(rel)
                if check_root and (result["uid"] == 0 or result["gid"] == 0):
                    file_root_issues.append(rel)

    for rel in baseline_files:
        if rel not in current_files:
            file_missing.append(rel)

    for rel in current_files:
        if rel not in baseline_files:
            file_extra.append(rel)

    elapsed = time.time() - start_time

    # 列印 summary
    print(f"--- Summary ---")
    print(f"Start time         : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
    print(f"Elapsed time       : {elapsed:.2f} seconds")
    print(f"Dirs baseline      : {total_dirs_baseline}")
    print(f"Dirs current       : {total_dirs_current}")
    print(f"Files baseline     : {total_files_baseline}")
    print(f"Files current      : {total_files_current}")
    print(f"----------------")

    # 目錄級別報告
    if dir_missing:
        print("\nMissing directories (in baseline but not on disk):")
        for d in dir_missing:
            print(f"  - {d}")
    if dir_extra:
        print("\nExtra directories (on disk but not in baseline):")
        for d in dir_extra:
            print(f"  + {d}")
    if dir_meta_mismatch:
        print("\nDirectories with metadata errors:")
        for rel, err in dir_meta_mismatch:
            print(f"  ! {rel}: {err}")

    # 檔案級別報告
    if file_missing:
        print("\nMissing files (in baseline but not on disk):")
        for f in file_missing:
            print(f"  - {f}")
    if file_extra:
        print("\nExtra files (on disk but not in baseline):")
        for f in file_extra:
            print(f"  + {f}")
    if file_error:
        print("\nFiles with errors (could not read):")
        for f in file_error:
            print(f"  ! {f}")
    if file_hash_mismatch:
        print("\nFiles with HASH mismatches:")
        for f in file_hash_mismatch:
            print(f"  ✗ {f}")
    if file_size_mismatch:
        print("\nFiles with Size mismatches:")
        for f in file_size_mismatch:
            print(f"  ✗ {f}")
    if not is_windows:
        if file_uid_mismatch:
            print("\nFiles with UID mismatches:")
            for f in file_uid_mismatch:
                print(f"  ✗ {f}")
        if file_gid_mismatch:
            print("\nFiles with GID mismatches:")
            for f in file_gid_mismatch:
                print(f"  ✗ {f}")
        if file_mode_mismatch:
            print("\nFiles with Mode mismatches:")
            for f in file_mode_mismatch:
                print(f"  ✗ {f}")
        if file_idmap_issues:
            print("\nFiles flagged for ID mapping issues (UID/GID=65534):")
            for f in file_idmap_issues:
                print(f"  ! {f}")
        if file_root_issues:
            print("\nFiles flagged for Root Squash issues (UID/GID=0):")
            for f in file_root_issues:
                print(f"  ! {f}")
    print(f"----------------")

# === CLI 入口 ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Universal integrity checker: directory & file (Linux/Windows mode)"
    )
    parser.add_argument(
        "mode", choices=["baseline", "verify"],
        help="Mode: baseline 或 verify"
    )
    parser.add_argument(
        "--path", required=True,
        help="要掃描的目錄 (Linux: /export/shared, Windows: Z:\\shared 或 \\\\nas-ip\\shared)"
    )
    parser.add_argument(
        "--threads", type=int, default=4,
        help="並行計算的執行緒數"
    )
    parser.add_argument(
        "--log", default=None,
        help="日誌檔案路徑 (baseline: 輸出; verify: 輸入)。預設為 <path>/.integrity_hash.log"
    )
    parser.add_argument(
        "--check-idmap", action="store_true",
        help="僅 Linux verify 時，如發現 UID/GID=65534 (nobody/nogroup) 會警告"
    )
    parser.add_argument(
        "--check-root", action="store_true",
        help="僅 Linux verify 時，如發現 UID/GID=0 (root) 會警告"
    )
    parser.add_argument(
        "--windows", action="store_true",
        help="啟用 Windows 模式：baseline/verify 僅比對 hash+size，路徑轉 POSIX(/) 風格"
    )

    args = parser.parse_args()
    base_path = Path(args.path)
    if not base_path.exists():
        print(f"❌ Path not found: {base_path}")
        exit(1)

    hash_log_path = Path(args.log) if args.log else base_path / HASH_LOG_NAME

    if args.mode == "baseline":
        generate_baseline(base_path, hash_log_path, args.threads, args.windows)
    else:
        if not hash_log_path.exists():
            print(f"❌ Log file not found: {hash_log_path}")
            exit(1)
        verify_integrity(
            base_path, hash_log_path, args.threads,
            args.check_idmap, args.check_root, args.windows
        )