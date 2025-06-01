#!/usr/bin/env python3
import os
import random
import argparse
import math
from pathlib import Path

def generate_random_file(file_path, size_bytes):
    """
    Write random bytes of length size_bytes to the specified file_path.
    """
    with open(file_path, "wb") as f:
        remaining = size_bytes
        chunk_size = 64 * 1024  # write in 64 KB chunks
        while remaining > 0:
            write_size = min(chunk_size, remaining)
            f.write(os.urandom(write_size))
            remaining -= write_size

def main():
    parser = argparse.ArgumentParser(
        description="Generate test files and optional multi-level directories"
    )
    parser.add_argument(
        "--base-dir", required=True,
        help="Output directory (e.g., /mnt/nfs_shared/test_data)"
    )
    parser.add_argument(
        "--file-count", type=int, default=100000,
        help="Total number of random files to create (default: 100000)"
    )
    parser.add_argument(
        "--max-total-size", type=float, default=5.0,
        help="Maximum total size in GiB for all random files (default: 5.0 GiB)"
    )
    parser.add_argument(
        "--min-size-kb", type=int, default=10,
        help="Minimum size of each random file in KB (default: 10 KB)"
    )
    parser.add_argument(
        "--max-size-kb", type=int, default=50,
        help="Maximum size of each random file in KB (default: 50 KB)"
    )
    parser.add_argument(
        "--subdir-count", type=int, default=1000,
        help="Number of single-level subdirectories to distribute random files into (default: 1000)"
    )
    parser.add_argument(
        "--multi-dir-count", type=int, default=0,
        help="Number of multi-level directories to create (default: 0)"
    )
    parser.add_argument(
        "--multi-dir-depth", type=int, default=2,
        help="Depth (number of nested levels) for each multi-level directory (default: 2)"
    )
    parser.add_argument(
        "--files-per-multi-dir", type=int, default=3,
        help="Number of random files to place inside each multi-level directory (default: 3)"
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    file_count = args.file_count
    max_total_size_bytes = int(args.max_total_size * 1024**3)  # GiB → bytes
    min_size = args.min_size_kb * 1024
    max_size = args.max_size_kb * 1024
    subdir_count = args.subdir_count
    multi_dir_count = args.multi_dir_count
    multi_dir_depth = args.multi_dir_depth
    files_per_multi = args.files_per_multi_dir

    # Create base directory
    base_dir.mkdir(parents=True, exist_ok=True)

    # === Part 1: Generate random files across single-level subdirectories ===
    files_per_subdir = math.ceil(file_count / subdir_count)
    total_written = 0
    files_created = 0

    for subidx in range(subdir_count):
        if files_created >= file_count:
            break

        subdir_name = f"subdir_{subidx:03d}"
        subdir_path = base_dir / subdir_name
        subdir_path.mkdir(exist_ok=True)

        to_create = min(files_per_subdir, file_count - files_created)
        for _ in range(to_create):
            if total_written >= max_total_size_bytes:
                break

            remaining_budget = max_total_size_bytes - total_written
            size_upper = min(max_size, remaining_budget)
            if size_upper < min_size:
                break

            size_bytes = random.randint(min_size, size_upper)
            filename = f"file_{files_created+1:06d}.dat"
            file_path = subdir_path / filename

            generate_random_file(file_path, size_bytes)
            total_written += size_bytes
            files_created += 1

        if files_created >= file_count or total_written >= max_total_size_bytes:
            break

    # === Part 2: Create multi-level directories if requested ===
    for idx in range(1, multi_dir_count + 1):
        # Build a nested path like base_dir/multidir_XXX/level1/level2/... up to depth
        idx_str = f"{idx:03d}"
        nested = base_dir / f"multidir_{idx_str}"
        for depth in range(1, multi_dir_depth + 1):
            nested = nested / f"level{depth}"
        nested.mkdir(parents=True, exist_ok=True)

        # Inside the deepest folder, create a few random files
        for j in range(1, files_per_multi + 1):
            # Each file size is a random choice between min_size and max_size, 
            # but do not exceed remaining budget
            if total_written < max_total_size_bytes:
                remaining_budget = max_total_size_bytes - total_written
                size_upper = min(max_size, remaining_budget)
                if size_upper < min_size:
                    break
                size_bytes = random.randint(min_size, size_upper)
            else:
                # If overall budget is exhausted, default to min_size
                size_bytes = min_size

            fname = f"file_multi_{idx_str}_{j}.dat"
            fpath = nested / fname
            generate_random_file(fpath, size_bytes)
            total_written += size_bytes
            # Note: these multi-dir files do not count against file_count

    # === Final summary ===
    print("--- Generation Summary ---")
    print(f"Base directory         : {base_dir}")
    print(f"Requested total files  : {file_count}")
    print(f"Files created in subdirs: {files_created}")
    print(f"Max total size         : {args.max_total_size} GiB")
    print(f"Total bytes written    : {total_written} bytes ({total_written/1024**3:.2f} GiB)")
    print(f"Single-level subdirs   : {subdir_count}")
    print(f"Multi-level directories: {multi_dir_count} (each depth={multi_dir_depth})")
    print(f"Files per multi-dir    : {files_per_multi}")
    print("--------------------------")

if __name__ == "__main__":
    main()
