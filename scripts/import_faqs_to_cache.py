import sys
import os

from dotenv import load_dotenv

# Add the src directory to the python path so we can import our services
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(project_root, "src")
sys.path.insert(0, src_dir)

load_dotenv(os.path.join(project_root, ".env"))

from infrastructure.llm.embeddings import get_default_embeddings
from services.chat_service.cag_cache import CAGCache

def main():
    print("Initialize embeddings...")
    embedder = get_default_embeddings()
    
    print("Initialize CAGCache...")
    cache = CAGCache(embedder=embedder)
    
    if not cache.available:
        print("CAG cache is not available! Check qdrant configurations.")
        return
    
    json_path = os.path.join(project_root, "data", "kapruka_all_faqs.json")
    print(f"Importing FAQs from {json_path} ...")
    
    count = cache.import_faqs(json_path)
    
    print(f"Successfully imported {count} FAQs into CAG semantic cache!")
    
if __name__ == "__main__":
    main()
