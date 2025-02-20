# STONECUTTER
## GeoTIFF to AWS S3 IIIF Image API Converter

This script converts GeoTIFF files to IIIF-compliant image tiles and uploads them to Amazon S3. It also optimizes the JPEG tiles using mozjpeg and integrates OpenGeoMetadata Aardvark metadata into the IIIF manifest.

## Prerequisites

- Python 3.8 or higher
- libvips library (required for pyvips)
  - On Ubuntu/Debian: `sudo apt-get install libvips`
  - On macOS: `brew install vips`
  - On Windows: Download from the libvips website
- mozjpeg (required for JPEG optimization)
  - On macOS: `brew install mozjpeg`
  - On Ubuntu/Debian: `sudo apt-get install mozjpeg`

## Installation

1. Create a virtual environment:
   ```
   python3 -m venv venv
   ```

2. Activate the virtual environment:
   - On Unix/macOS: `source venv/bin/activate`
   - On Windows: `venv\Scripts\activate`

3. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a .env file with your AWS credentials and settings:
   ```
   # AWS credentials
   AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
   AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
   AWS_REGION=YOUR_AWS_REGION
   AWS_BUCKET_NAME=YOUR_AWS_BUCKET_NAME
   AWS_S3_PREFIX=YOUR_AWS_S3_PREFIX
   AWS_IIIF_BASE_URL=YOUR_AWS_IIIF_BASE_URL

   # Output directory
   OUTPUT_DIR=output_files
   ```

## Input Directory Structure

The script expects an input directory containing:
1. A GeoTIFF file (*.tif)
2. An OpenGeoMetadata Aardvark JSON file (*.json)

Example:
```
input_files/
  └── ANT-REF-MT2503-020/
      ├── davis_valley.tif
      └── davis_valley.json
```

## Usage

The script can be used in two modes:

1. Generate and upload tiles (default):
   ```
   python main.py input_files/ANT-REF-MT2503-020 --tile_and_upload
   ```

2. Generate manifest only (useful for testing):
   ```
   python main.py input_files/ANT-REF-MT2503-020
   ```

### Arguments:
- `input_directory`: Directory containing GeoTIFF and metadata JSON files (required)
- `--tile_and_upload`: Flag to generate tiles and upload to S3 (optional)
- `--jpeg-quality`: JPEG quality for tiles (1-100, default: 80)
- `--optimization-workers`: Number of parallel optimization workers (default: 4)
- `--no-progress`: Disable progress bars

### Output:
- Creates IIIF-compliant image tiles in the output_tiles directory
- Optimizes JPEG tiles using mozjpeg
- Uploads tiles and manifest to S3 under the specified prefix
- Generates a IIIF manifest.json file enhanced with OpenGeoMetadata
- Makes all files publicly accessible via S3

## Development

### Code Quality Tools

This project uses several tools to maintain code quality:

1. **Black** - Code formatter
   - Automatically formats Python code to a consistent style
   - Run manually: `black .`

2. **Ruff** - Fast Python linter
   - Checks code for errors and style violations
   - Run manually: `ruff check .`
   - Auto-fix issues: `ruff check --fix .`

3. **MyPy** - Static type checker
   - Verifies type hints and catches type-related errors
   - Run manually: `mypy .`

### Setting Up Development Environment

1. Install development dependencies:
   ```
   pip install -r requirements-dev.txt
   ```

2. Install pre-commit hooks:
   ```
   pip install pre-commit
   pre-commit install
   ```

The pre-commit hooks will automatically:
- Format code using Black
- Run Ruff linter
- Check types with MyPy
- Fix trailing whitespace and file endings
- Verify YAML files
- Check for large files

## Notes

- The script creates a Level 0 IIIF Image API compliant service
- Files are uploaded with public-read ACL to S3
- Make sure your S3 bucket has appropriate permissions and CORS settings
- The output directory is cleaned before each run
- JPEG tiles are optimized using mozjpeg for smaller file sizes
- OpenGeoMetadata fields are mapped to IIIF manifest metadata
