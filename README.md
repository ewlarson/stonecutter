# STONECUTTER
## GeoTIFF to AWS S3 IIIF Image API Converter

This script converts GeoTIFF files to IIIF-compliant image tiles and uploads them to Amazon S3.

## Prerequisites

- Python 3.6 or higher
- libvips library (required for pyvips)
  - On Ubuntu/Debian: sudo apt-get install libvips
  - On macOS: brew install vips
  - On Windows: Download from the libvips website

## Installation

1. Create a virtual environment:
   python3 -m venv venv

2. Activate the virtual environment:
   - On Unix/macOS: source venv/bin/activate
   - On Windows: venv\Scripts\activate

3. Install the dependencies:
   pip install -r requirements.txt

4. Create a .env file with your AWS credentials and settings:

   # AWS credentials
   AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
   AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
   AWS_REGION=YOUR_AWS_REGION
   AWS_BUCKET_NAME=YOUR_AWS_BUCKET_NAME
   AWS_S3_PREFIX=YOUR_AWS_S3_PREFIX
   AWS_IIIF_BASE_URL=YOUR_AWS_IIIF_BASE_URL

   # Output directory
   OUTPUT_DIR=output_files

   # Input directory
   INPUT_DIR=input_files

## Usage

The script can be used in two modes:

1. Generate and upload tiles (default):
   python main.py path/to/your/geotiff.tif --tile_and_upload

2. Generate manifest only (useful for testing):
   python main.py path/to/your/geotiff.tif

### Arguments:
- input_geotiff: Path to the input GeoTIFF file (required)
- --tile_and_upload: Flag to generate tiles and upload to S3 (optional)

### Output:
- Creates IIIF-compliant image tiles in the output_tiles directory
- Uploads tiles and manifest to S3 under the specified prefix
- Generates a IIIF manifest.json file
- Makes all files publicly accessible via S3

### Example:
python main.py sample.tif --tile_and_upload

## Notes

- The script creates a Level 0 IIIF Image API compliant service
- Files are uploaded with public-read ACL to S3
- Make sure your S3 bucket has appropriate permissions and CORS settings
- The output directory (output_tiles) is cleaned before each run

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

### Running Code Quality Checks

You can run all checks manually:
