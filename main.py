#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, Optional, List, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import glob

import boto3  # type: ignore  # missing stubs
import pyvips  # type: ignore  # missing stubs
from dotenv import load_dotenv
from mozjpeg_lossless_optimization import optimize  # type: ignore  # missing stubs

# Load environment variables from .env file
load_dotenv()


def optimize_single_jpeg(jpeg_file: Path) -> Tuple[Path, int]:
    """
    Optimize a single JPEG file using mozjpeg.

    Args:
        jpeg_file: Path to the JPEG file

    Returns:
        Tuple of (file path, bytes saved)
    """
    original_size = os.path.getsize(jpeg_file)
    with open(jpeg_file, "rb") as f:
        optimized_data = optimize(f.read())

    if len(optimized_data) < original_size:
        with open(jpeg_file, "wb") as f:
            f.write(optimized_data)
        return jpeg_file, original_size - len(optimized_data)
    return jpeg_file, 0


def optimize_jpeg_tiles(
    directory: str, max_workers: int = 4, show_progress: bool = True
) -> None:
    """
    Optimize all JPEG files in a directory tree using mozjpeg with parallel processing.

    Args:
        directory: Root directory containing JPEG files to optimize
        max_workers: Number of parallel optimization workers
        show_progress: Whether to show progress bars
    """
    # Get list of all jpg files
    jpeg_files = list(Path(directory).rglob("*.jpg"))
    total_saved = 0
    processed_files = 0

    # Create progress bar
    pbar = tqdm(
        total=len(jpeg_files), desc="Optimizing tiles", disable=not show_progress
    )

    # Process files in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all optimization jobs
        future_to_file = {
            executor.submit(optimize_single_jpeg, jpeg_file): jpeg_file
            for jpeg_file in jpeg_files
        }

        # Process results as they complete
        for future in as_completed(future_to_file):
            file_path, saved = future.result()
            total_saved += saved
            processed_files += 1
            if saved > 0:
                pbar.write(f"Optimized {file_path.name}: saved {saved/1024:.1f}KB")
            pbar.update(1)

    pbar.close()
    print(
        f"Processed {processed_files} files. "
        f"Total space saved: {total_saved/1024/1024:.1f}MB"
    )


def load_metadata(directory: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Load GeoTIFF and metadata files from directory.

    Args:
        directory: Path to directory containing .tif and .json files

    Returns:
        Tuple of (tiff_path, metadata_dict, base_name)
    """
    # Find the first .tif file
    tiff_files = glob.glob(os.path.join(directory, "*.tif"))
    if not tiff_files:
        raise FileNotFoundError(f"No .tif file found in {directory}")
    tiff_path = tiff_files[0]

    # Find the first .json file
    json_files = glob.glob(os.path.join(directory, "*.json"))
    if not json_files:
        raise FileNotFoundError(f"No .json file found in {directory}")

    # Load the metadata
    with open(json_files[0], "r") as f:
        metadata = json.load(f)

    # Get base name from the directory
    base_name = os.path.basename(directory)

    return tiff_path, metadata, base_name


def enhance_manifest_with_metadata(
    manifest: Dict[str, Any], metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Enhance IIIF manifest with OpenGeoMetadata fields.

    Args:
        manifest: Original IIIF manifest
        metadata: OpenGeoMetadata record

    Returns:
        Enhanced IIIF manifest
    """
    # Update basic fields
    manifest["label"] = metadata.get("dct_title_s", manifest["label"])

    # Build rich metadata array
    iiif_metadata = []

    # Map OpenGeoMetadata fields to IIIF metadata labels
    field_mappings = {
        "dct_description_sm": "Description",
        "dct_publisher_sm": "Publisher",
        "schema_provider_s": "Provider",
        "gbl_resourceClass_sm": "Resource Class",
        "gbl_resourceType_sm": "Resource Type",
        "dct_temporal_sm": "Temporal Coverage",
        "dct_issued_s": "Date Issued",
        "dct_spatial_sm": "Spatial Coverage",
        "dct_format_s": "Format",
        "geomg_id_s": "Identifier",
        "dct_language_sm": "Language",
    }

    for field, label in field_mappings.items():
        value = metadata.get(field)
        if value:
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            iiif_metadata.append({"label": label, "value": value})

    # Add spatial extent if available
    if "locn_geometry" in metadata:
        iiif_metadata.append(
            {"label": "Geographic Extent", "value": metadata["locn_geometry"]}
        )

    # Update manifest metadata
    manifest["metadata"] = iiif_metadata

    return manifest


def convert_geotiff_to_iiif(
    input_geotiff: str,
    output_dir: str,
    bucket_name: str,
    s3_prefix: str,
    metadata: Dict[str, Any],  # Add metadata parameter
    base_name: str,  # Add base_name parameter
    region_name: str = "us-east-1",
    endpoint_url: Optional[str] = None,
    aws_access_key_id: Optional[str] = None,
    aws_secret_access_key: Optional[str] = None,
    iiif_base_url: Optional[str] = None,
    title: str = "My GeoTIFF as IIIF",
    creator: str = "Unknown",
    tile_and_upload: bool = True,
    jpeg_quality: int = 80,
    optimization_workers: int = 4,
    show_progress: bool = True,
) -> Dict[str, Any]:
    """
    1) Converts a GeoTIFF to IIIF-compliant tile folders (static).
    2) Uploads files to S3 under s3://bucket_name/s3_prefix/.
    3) Generates a minimal IIIF Presentation API Manifest (JSON).

    Args:
        input_geotiff: Path to input GeoTIFF file.
        output_dir: Local output folder for IIIF tiles.
        bucket_name: Name of the S3 bucket.
        s3_prefix: Prefix (folder path in S3) for uploaded files.
        region_name: AWS region (default "us-east-1").
        endpoint_url: Optional custom endpoint (e.g., for S3-compatible storage).
        aws_access_key_id: AWS access key.
        aws_secret_access_key: AWS secret key.
        iiif_base_url: Base HTTPS URL that points to your S3 tile root
            (e.g. https://<bucket>.s3.amazonaws.com/<prefix>).
            This is used in the manifest to reference the tiles.
        title: Title of the work in the IIIF Manifest.
        creator: Creator/attribution in the IIIF Manifest.
        tile_and_upload: Whether to tile and upload images.
        jpeg_quality: JPEG quality (1-100, default: 80)
        optimization_workers: Number of parallel optimization workers (default: 4)
        show_progress: Whether to show progress bars

    Returns:
        A Python dict representing the IIIF Manifest.
    """

    # ------------------------------------------------------------------
    # 1) Convert GeoTIFF -> IIIF tile folders
    # ------------------------------------------------------------------
    # The "dzsave" method will create a folder structure that matches
    # the IIIF Image API (by specifying `layout="iiif"`).
    # The main directory will have:
    #     - info.json (contains image dimensions & tile info)
    #     - subfolders for each zoom level, each containing tiles
    # Example:
    #     my_image/
    #       ├─ info.json
    #       ├─ 0/
    #       ├─ 1/
    #       ├─ 2/
    #       └─ ...
    #
    # "access='sequential'" is often recommended for large images.
    # Depending on your GeoTIFF, you may need to specify `n=-1` or
    # other options to handle multi-band data.

    dz_output_folder = os.path.join(output_dir, base_name)

    # Load the image regardless of the tile_and_upload flag
    image = pyvips.Image.new_from_file(input_geotiff, access="sequential")

    # Initialize the S3 session and bucket regardless of the tile_and_upload flag
    session = boto3.session.Session(
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )
    s3 = session.resource("s3", endpoint_url=endpoint_url)
    bucket = s3.Bucket(bucket_name)

    if tile_and_upload:
        # Clean up any existing folder to ensure a fresh output
        if os.path.exists(dz_output_folder):
            shutil.rmtree(dz_output_folder)

        print(f"Creating IIIF tiles from {input_geotiff} ...")
        image.dzsave(
            dz_output_folder,
            layout="iiif",
            suffix=".jpg",  # tile format (JPEG)
            overlap=0,  # overlap in pixels between tiles
            tile_size=256,  # typical tile size for IIIF
            Q=jpeg_quality,  # JPEG quality from parameter
            strip=True,  # Remove EXIF metadata
        )
        print(f"IIIF tiles created at: {dz_output_folder}")

        print(f"Optimizing JPEG tiles with mozjpeg...")
        optimize_jpeg_tiles(
            dz_output_folder,
            max_workers=optimization_workers,
            show_progress=show_progress,
        )

        # Modify the info.json file to use the correct @id
        info_json_path = os.path.join(dz_output_folder, "info.json")
        with open(info_json_path, "r") as f:
            info_data = json.load(f)

        # Update the @id with the correct URL using environment variables
        info_data["@id"] = (
            f"{os.getenv('AWS_IIIF_BASE_URL')}/{os.getenv('AWS_S3_PREFIX')}/{base_name}"
        )

        sys.stdout.write(json.dumps(info_data, indent=2) + "\n")

        # Write the modified info.json back
        with open(info_json_path, "w") as f:
            json.dump(info_data, f, indent=2)

        # Upload the tile folder to S3
        print(f"Uploading tiles to s3://{bucket_name}/{s3_prefix} ...")
        for root, _, files in os.walk(dz_output_folder):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, output_dir)
                s3_key = os.path.join(s3_prefix, relative_path).replace("\\", "/")

                bucket.upload_file(
                    local_path,
                    s3_key,
                    ExtraArgs={
                        "ContentType": content_type_from_extension(filename),
                        "ACL": "public-read",
                    },
                )
        print("Upload complete.")

    # The dzsave call produces:
    #    dz_output_folder/info.json
    # plus subfolders for each zoom level.

    # ------------------------------------------------------------------
    # 3) Read the IIIF "info.json" and create a Presentation Manifest
    # ------------------------------------------------------------------
    # For convenience, let's define the direct URL of info.json on S3
    if not iiif_base_url:
        # Fallback: try to guess an https endpoint if none given
        iiif_base_url = f"https://{bucket_name}.s3.amazonaws.com"

    # Construct the full service ID for this image
    image_service_id = (
        f"{os.getenv('AWS_IIIF_BASE_URL')}/"
        f"{os.getenv('AWS_S3_PREFIX')}/"
        f"{base_name}"
    )

    # Create a level 0 compliant info.json
    info_data = {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": image_service_id,  # Use the full service ID here
        "protocol": "http://iiif.io/api/image",
        "width": image.width,
        "height": image.height,
        "profile": ["http://iiif.io/api/image/2/level0.json"],
        "sizes": [{"width": image.width, "height": image.height}],
        "tiles": [{"width": 256, "scaleFactors": [1]}],
    }

    # Construct manifest with correct image service URLs
    manifest_id = f"{image_service_id}/manifest.json"
    canvas_id = f"{manifest_id}/canvas/p1"
    image_annotation_id = f"{canvas_id}/image"

    # Create manifest with metadata
    manifest = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": manifest_id,
        "label": metadata.get("dct_title_s", "Untitled"),  # Use title from metadata
        "metadata": [{"label": "Creator", "value": creator}],
        "sequences": [
            {
                "@type": "sc:Sequence",
                "canvases": [
                    {
                        "@type": "sc:Canvas",
                        "@id": canvas_id,
                        "label": "p. 1",
                        "height": image.height,
                        "width": image.width,
                        "images": [
                            {
                                "@type": "oa:Annotation",
                                "motivation": "sc:painting",
                                "@id": image_annotation_id,
                                "resource": {
                                    "@id": f"{image_service_id}/full/full/0/default.jpg",
                                    "@type": "dctypes:Image",
                                    "format": "image/jpeg",
                                    "height": image.height,
                                    "width": image.width,
                                    "service": {
                                        "@context": "http://iiif.io/api/image/2/context.json",
                                        "@id": image_service_id,
                                        "profile": "http://iiif.io/api/image/2/level0.json",
                                    },
                                },
                                "on": canvas_id,
                            }
                        ],
                    }
                ],
            }
        ],
    }

    # Enhance manifest with metadata
    manifest = enhance_manifest_with_metadata(manifest, metadata)

    # Save the manifest
    manifest_path = os.path.join(dz_output_folder, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Save the info.json
    info_json_path = os.path.join(dz_output_folder, "info.json")
    with open(info_json_path, "w", encoding="utf-8") as f:
        json.dump(info_data, f, indent=2)

    # ------------------------------------------------------------------
    # 4) Save and upload the info.json and manifest.json to S3
    # ------------------------------------------------------------------
    # Upload info.json
    info_json_s3_key = os.path.join(s3_prefix, base_name, "info.json").replace(
        "\\", "/"
    )
    bucket.upload_file(
        info_json_path,
        info_json_s3_key,
        ExtraArgs={"ContentType": "application/json", "ACL": "public-read"},
    )

    # Upload manifest.json
    manifest_s3_key = os.path.join(s3_prefix, base_name, "manifest.json").replace(
        "\\", "/"
    )
    bucket.upload_file(
        manifest_path,
        manifest_s3_key,
        ExtraArgs={"ContentType": "application/json", "ACL": "public-read"},
    )

    print(f"IIIF Manifest uploaded to s3://{bucket_name}/{manifest_s3_key}")
    print(f"Public URL (if your bucket is public): {manifest_id}")

    return manifest


def content_type_from_extension(filename: str) -> str:
    """
    Basic helper to guess Content-Type from file extension.

    Args:
        filename: The name of the file including extension

    Returns:
        The MIME type as a string
    """
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ["jpg", "jpeg"]:
        return "image/jpeg"
    elif ext == "png":
        return "image/png"
    elif ext == "json":
        return "application/json"
    elif ext == "tif" or ext == "tiff":
        return "image/tiff"
    else:
        return "binary/octet-stream"


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Convert GeoTIFF to IIIF tiles and upload to S3."
    )
    parser.add_argument(
        "input_directory", help="Directory containing GeoTIFF and metadata JSON files"
    )
    parser.add_argument(
        "--tile_and_upload", action="store_true", help="Tile and upload images if set"
    )
    parser.add_argument(
        "--jpeg-quality", type=int, default=80, help="JPEG quality (1-100, default: 80)"
    )
    parser.add_argument(
        "--optimization-workers",
        type=int,
        default=4,
        help="Number of parallel optimization workers (default: 4)",
    )
    parser.add_argument(
        "--no-progress", action="store_true", help="Disable progress bars"
    )
    args = parser.parse_args()

    # Example usage
    # Adjust these variables to match your environment
    INPUT_DIRECTORY = args.input_directory
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output_tiles")
    BUCKET_NAME = os.getenv("AWS_BUCKET_NAME", "my-iiif-bucket")
    AWS_S3_PREFIX = os.getenv("AWS_S3_PREFIX", "my_geotiff")
    AWS_IIIF_BASE_URL = os.getenv(
        "AWS_IIIF_BASE_URL", "https://my-iiif-bucket.s3.amazonaws.com/my_geotiff"
    )

    # Load AWS credentials from .env file
    AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    REGION_NAME = os.getenv("AWS_REGION", "us-east-1")

    # Load files from directory
    tiff_path, metadata, base_name = load_metadata(INPUT_DIRECTORY)

    convert_geotiff_to_iiif(
        input_geotiff=tiff_path,
        output_dir=OUTPUT_DIR,
        bucket_name=BUCKET_NAME,
        s3_prefix=AWS_S3_PREFIX,
        metadata=metadata,
        base_name=base_name,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        iiif_base_url=AWS_IIIF_BASE_URL,
        tile_and_upload=args.tile_and_upload,
        jpeg_quality=args.jpeg_quality,
        optimization_workers=args.optimization_workers,
        show_progress=not args.no_progress,
    )
