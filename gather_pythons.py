import os
from datetime import datetime

# Configuration
# Set file types to include
FILE_EXTENSIONS = [
    '.py',    # Python files (always included)
    '.html',  # HTML files
    '.js',    # JavaScript files
    #'.css',   # CSS files
    #'.json',  # JSON configuration files
]

# Flag to control directory depth
ONLY_ROOT_DIRECTORY = False  # Set to True to only search in root directory

# Filename patterns to exclude (new)
EXCLUDED_FILENAME_PATTERNS = [
    'copy',   # Any file with 'copy' in the name
    'backup', # Any file with 'backup' in the name
    'temp',   # Any file with 'temp' in the name
        'archives',   # Any file with 'temp' in the name
                '_full',   # Any file with '_full' in the name
]

# Directories to completely exclude from both scanning and output
EXCLUDED_DIRECTORIES = [
    "assets",
    "tests",
    "previous_versions",
    "projects",
    "tools",
    "revisions_app",
    "venv_2man",
    ".git",
    "archives"

]

def gather_files(root_dir, excluded_directories, file_extensions, excluded_patterns, only_root=False):
    """
    Gathers files with specified extensions within the root directory and its subdirectories,
    excluding specified directories and filename patterns.

    Parameters:
        root_dir (str): The root directory to search for files.
        excluded_directories (list): List of directory names to exclude.
        file_extensions (list): List of file extensions to include.
        excluded_patterns (list): List of filename patterns to exclude.
        only_root (bool): If True, only search in the root directory (no subdirectories).

    Returns:
        tuple: (files_data, included_directories)
    """
    files_data = []
    included_directories = set()

    if only_root:
        # Only process files in the root directory
        relative_path = "."
        included_directories.add(relative_path)
        
        try:
            filenames = os.listdir(root_dir)
            for filename in filenames:
                file_path = os.path.join(root_dir, filename)
                
                # Skip directories
                if os.path.isdir(file_path):
                    continue
                
                # Skip files with excluded patterns in the filename
                if any(pattern.lower() in filename.lower() for pattern in excluded_patterns):
                    continue
                    
                # Only include files with the specified extensions
                if any(filename.endswith(ext) for ext in file_extensions):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as file:
                            file_contents = file.read()
                        files_data.append((file_path, file_contents))
                    except UnicodeDecodeError:
                        print(f"Could not read file {file_path} due to encoding error. Skipping.")
                    except Exception as e:
                        print(f"Error with file {file_path}: {e}")
        except Exception as e:
            print(f"Error accessing root directory: {e}")
    else:
        # Original recursive behavior
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Get the relative path
            relative_path = os.path.relpath(dirpath, root_dir)
            
            # Skip excluded directories - check if any part of the path matches exclusion patterns
            should_exclude = False
            for excluded_dir in excluded_directories:
                # Check both exact match and path-based matches
                if excluded_dir == relative_path or excluded_dir in relative_path.replace('\\', '/'):
                    should_exclude = True
                    break
                    
            if should_exclude:
                continue

            # Add directory to our structure
            included_directories.add(relative_path)
            
            # Process files
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                
                # Skip files with excluded patterns in the filename
                if any(pattern.lower() in filename.lower() for pattern in excluded_patterns):
                    continue
                    
                # Only include files with the specified extensions
                if any(filename.endswith(ext) for ext in file_extensions):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as file:
                            file_contents = file.read()
                        files_data.append((file_path, file_contents))
                    except UnicodeDecodeError:
                        print(f"Could not read file {file_path} due to encoding error. Skipping.")
                    except Exception as e:
                        print(f"Error with file {file_path}: {e}")

    return files_data, sorted(included_directories)

def write_to_file(output_filepath, files_data, included_directories):
    """
    Writes the gathered data to a file with project information and file contents.
    """
    with open(output_filepath, 'w', encoding='utf-8') as file:
        # Write statistics
        file.write(f"Number of files: {len(files_data)}\n")
        file.write(f"Number of directories: {len(included_directories)}\n\n")
        
        # Write directory structure
        file.write("Directory structure:\n")
        for directory in included_directories:
            file.write(f"{directory}\n")
        file.write("\n")
        
        # Group and list files by extension
        extension_groups = {}
        for filepath, _ in files_data:
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in extension_groups:
                extension_groups[ext] = []
            extension_groups[ext].append(filepath)
        
        file.write("List of file paths by type:\n")
        for ext, filepaths in sorted(extension_groups.items()):
            file.write(f"\n{ext.upper()[1:]} Files ({len(filepaths)}):\n")
            for filepath in sorted(filepaths):
                file.write(f"  {filepath}\n")
        file.write("\n")
        
        # Write file contents
        file.write("="*80 + "\n")
        file.write("FILE CONTENTS\n")
        file.write("="*80 + "\n\n")
        
        for filepath, file_contents in files_data:
            file.write(f"FILE: {filepath}\n")
            file.write("-"*80 + "\n")
            file.write(f"{file_contents}\n\n")
            file.write("="*80 + "\n\n")

def scan_project_structure():
    """
    Main function to scan the project structure and write the results to a file.
    """
    root_dir = "."  # Current directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filepath = f"{timestamp}_project_structure.txt"
    
    print(f"Starting to scan project structure at {root_dir}...")
    print(f"Including file types: {', '.join(FILE_EXTENSIONS)}")
    print(f"Excluding file patterns: {', '.join(EXCLUDED_FILENAME_PATTERNS)}")
    
    if ONLY_ROOT_DIRECTORY:
        print("Scanning ONLY root directory (subdirectories will be skipped)")
    else:
        print(f"Excluding directories: {', '.join(EXCLUDED_DIRECTORIES)}")
    
    # Gather files and directory information
    files_data, included_directories = gather_files(
        root_dir, 
        EXCLUDED_DIRECTORIES, 
        FILE_EXTENSIONS,
        EXCLUDED_FILENAME_PATTERNS,
        only_root=ONLY_ROOT_DIRECTORY
    )
    
    print(f"Found {len(files_data)} files across {len(included_directories)} directories.")
    if not ONLY_ROOT_DIRECTORY:
        print(f"Excluded directories won't appear in the output file.")
    
    # Write the output file
    write_to_file(
        output_filepath, 
        files_data, 
        included_directories
    )
    
    print(f"Project structure has been written to {output_filepath}")
    print(f"File size: {os.path.getsize(output_filepath) / (1024*1024):.2f} MB")

if __name__ == "__main__":
    scan_project_structure()