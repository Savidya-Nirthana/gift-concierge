import sys
import os

# Add the src directory to the python path so we can import our services
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(project_root, "src")
sys.path.insert(0, src_dir)

from services.ingest_service.faq_ingest import main

if __name__ == "__main__":
    # Get the data directory relative to the project root
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    output_path = os.path.join(data_dir, "kapruka_all_faqs.json")
    
    print(f"Starting FAQ ingestion...")
    print(f"Output will be saved to: {output_path}")
    main(output_file=output_path)
