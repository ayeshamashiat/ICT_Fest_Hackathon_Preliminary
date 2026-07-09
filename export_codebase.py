#!/usr/bin/env python3
"""
Script to export entire codebase and folder structure to a text file.
"""

import os
import sys
from pathlib import Path
from datetime import datetime


def should_skip(path):
    """Check if a file or directory should be skipped."""
    skip_dirs = {
        '__pycache__', '.git', '.venv', 'venv', 'env', 
        '.pytest_cache', '.egg-info', 'dist', 'build',
        '.env', '.DS_Store', '.vscode', 'node_modules'
    }
    skip_extensions = {'.pyc', '.pyo', '.pyd', '.so', '.o'}
    
    path_obj = Path(path)
    
    # Skip specific directories
    if path_obj.name in skip_dirs:
        return True
    
    # Skip specific file extensions
    if path_obj.suffix in skip_extensions:
        return True
    
    return False


def get_tree_structure(root_path, prefix="", is_last=True):
    """Generate tree structure representation."""
    lines = []
    try:
        entries = sorted([e for e in os.listdir(root_path) if not should_skip(os.path.join(root_path, e))])
    except PermissionError:
        return lines
    
    for i, entry in enumerate(entries):
        path = os.path.join(root_path, entry)
        is_last_entry = i == len(entries) - 1
        
        # Tree characters
        current_prefix = "└── " if is_last_entry else "├── "
        next_prefix = "    " if is_last_entry else "│   "
        
        lines.append(prefix + current_prefix + entry)
        
        # Recursively add subdirectories
        if os.path.isdir(path):
            lines.extend(get_tree_structure(path, prefix + next_prefix, is_last_entry))
    
    return lines


def export_codebase(root_path='.', output_file='codebase_export.txt'):
    """
    Export entire codebase to a text file.
    
    Args:
        root_path: Root directory to start from (default: current directory)
        output_file: Output filename (default: codebase_export.txt)
    """
    root_path = os.path.abspath(root_path)
    output_path = os.path.join(root_path, output_file)
    
    print(f"📁 Starting codebase export from: {root_path}")
    print(f"📝 Output file: {output_path}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # Header
        f.write("=" * 80 + "\n")
        f.write(f"CODEBASE EXPORT\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Root Path: {root_path}\n")
        f.write("=" * 80 + "\n\n")
        
        # Folder structure
        f.write("FOLDER STRUCTURE\n")
        f.write("-" * 80 + "\n\n")
        f.write(os.path.basename(root_path) + "/\n")
        
        tree_lines = get_tree_structure(root_path)
        for line in tree_lines:
            f.write(line + "\n")
        
        f.write("\n" + "=" * 80 + "\n\n")
        
        # File contents
        f.write("FILE CONTENTS\n")
        f.write("-" * 80 + "\n\n")
        
        file_count = 0
        
        # Walk through all files
        for dirpath, dirnames, filenames in os.walk(root_path):
            # Filter out directories to skip
            dirnames[:] = [d for d in dirnames if not should_skip(os.path.join(dirpath, d))]
            
            for filename in sorted(filenames):
                filepath = os.path.join(dirpath, filename)
                
                if should_skip(filepath):
                    continue
                
                # Get relative path
                rel_path = os.path.relpath(filepath, root_path)
                
                # Write file header
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"FILE: {rel_path}\n")
                f.write("=" * 80 + "\n")
                
                try:
                    # Try to read as text
                    with open(filepath, 'r', encoding='utf-8') as file:
                        content = file.read()
                        f.write(content)
                        if not content.endswith('\n'):
                            f.write('\n')
                        file_count += 1
                except (UnicodeDecodeError, PermissionError):
                    f.write("[Binary or inaccessible file]\n")
                    file_count += 1
        
        # Footer
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"END OF EXPORT\n")
        f.write(f"Total files exported: {file_count}\n")
        f.write("=" * 80 + "\n")
    
    print(f"✅ Export complete! {file_count} files written to {output_file}")


if __name__ == '__main__':
    # Parse command line arguments
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    output = sys.argv[2] if len(sys.argv) > 2 else 'codebase_export.txt'
    
    export_codebase(root, output)
