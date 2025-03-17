#!/usr/bin/env python3
import requests
from xml.etree import ElementTree
import sys
import os
import csv
import re
import time
import json
from urllib.parse import urlparse
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import openai

# Load environment variables from .env file
load_dotenv()

# Get configuration from environment variables
SITEMAP_URL = os.getenv('SITEMAP_URL')
INPUT_CSV = os.getenv('INPUT_CSV', 'codes.csv')
OUTPUT_CSV = os.getenv('OUTPUT_CSV', 'products.csv')
RECURSIVE = os.getenv('RECURSIVE', 'false').lower() == 'true'
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MAX_PRODUCTS = int(os.getenv('MAX_PRODUCTS', '0'))
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'  # Add debug flag
FORCE_MODE = os.getenv('FORCE_MODE', 'false').lower() == 'true'  # Force processing of all codes in CSV

# Configure OpenAI API
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    print("Warning: OpenAI API key not found in .env file. Translation functionality will be disabled.")

# Ensure the sitemap URL is provided
if not SITEMAP_URL:
    print("Error: No sitemap URL provided. Please set the SITEMAP_URL in the .env file.", file=sys.stderr)
    sys.exit(1)


def fetch_sitemap(url):
    """Fetch the sitemap XML from the given URL."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching sitemap: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_product_page(url):
    """Fetch the HTML content of a product page."""
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            print(f"  Fetching product page: {url} (attempt {attempt}/{max_retries})")
            response = requests.get(url, headers=headers, timeout=30)
            
            # Check if response is valid
            if response.status_code == 404:
                print(f"  Product page not found (404): {url}")
                return None
                
            response.raise_for_status()
            
            # Check if content is empty or too small (likely an error page)
            if len(response.text) < 1000:  # Arbitrary small size check
                print(f"  Warning: Response content too small ({len(response.text)} bytes), might not be a valid product page")
                
            return response.text
            
        except requests.exceptions.Timeout:
            print(f"  Timeout fetching product page (attempt {attempt}/{max_retries}): {url}")
            if attempt < max_retries:
                print(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"  Max retries reached. Giving up on: {url}")
                return None
                
        except requests.exceptions.ConnectionError:
            print(f"  Connection error fetching product page (attempt {attempt}/{max_retries}): {url}")
            if attempt < max_retries:
                print(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"  Max retries reached. Giving up on: {url}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"  Error fetching product page {url}: {e}")
            if attempt < max_retries:
                print(f"  Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"  Max retries reached. Giving up on: {url}")
                return None
    
    return None  # Should never reach here, but just in case


def parse_product_page(html_content):
    """
    Parse a product page HTML content to extract:
    - Product description
    - Product specifications
    - Items in set (if applicable)
    - Application cases (where mentioned)
    """
    if not html_content:
        return {"description": "", "specifications": {}, "items_in_set": [], "applications": []}
    
    soup = BeautifulSoup(html_content, 'lxml')
    result = {
        "description": "",
        "specifications": {},
        "items_in_set": [],
        "applications": []
    }
    
    # Debug: Save HTML to file for inspection and print div classes only if debugging is enabled
    if DEBUG:
        with open('debug_html.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Print all available div classes for debugging
        print("Available div classes:")
        for div in soup.find_all('div', class_=True):
            print(f"  - {div.get('class')}")
    
    # Try multiple possible selectors for product description
    description_selectors = [
        '.product-single__description', 
        '.product__description',
        '.product-description',
        '.description',
        '[itemprop="description"]',
        '.product-detail'
    ]
    
    for selector in description_selectors:
        description_div = soup.select_one(selector)
        if description_div:
            result["description"] = description_div.get_text(strip=True)
            print(f"Found description with selector: {selector}")
            
            # Try to find application cases in the description
            desc_text = description_div.get_text().lower()
            if any(kw in desc_text for kw in ['ideal for', 'perfect for', 'used for', 'designed for', 'suitable for', 'applications']):
                # There might be application information in the description
                result["applications"].append(description_div.get_text())
            break
    
    # Try multiple possible selectors for specifications
    spec_selectors = [
        '.product-single__specs-table',
        '.specs-table',
        '.product-specs',
        '.specifications',
        'table.specs',
        '[itemprop="additionalProperty"]'
    ]
    
    for selector in spec_selectors:
        spec_tables = soup.select(selector)
        if spec_tables:
            print(f"Found specifications with selector: {selector}")
            for table in spec_tables:
                # Try to find table rows
                rows = table.select('tr')
                for row in rows:
                    cells = row.select('td')
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        result["specifications"][key] = value
                        
                        # Check if any specification mentions applications
                        if any(app in key.lower() for app in ['application', 'use', 'usage', 'suitable']):
                            result["applications"].append(f"{key}: {value}")
            break
    
    # Alternative: Look for product metadata in JSON-LD
    json_ld = soup.find('script', type='application/ld+json')
    if json_ld:
        try:
            json_data = json.loads(json_ld.string)
            print("Found JSON-LD data")
            
            # Extract product info from JSON-LD
            if isinstance(json_data, dict):
                # Extract description if available
                if 'description' in json_data and not result["description"]:
                    result["description"] = json_data['description']
                
                # Extract other properties if available
                if 'additionalProperty' in json_data:
                    for prop in json_data['additionalProperty']:
                        if 'name' in prop and 'value' in prop:
                            result["specifications"][prop['name']] = prop['value']
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"  Error parsing JSON-LD: {e}")
    
    # If no specifications were found, look for any definition lists which often contain specs
    if not result["specifications"]:
        dl_elements = soup.find_all('dl')
        for dl in dl_elements:
            dts = dl.find_all('dt')
            dds = dl.find_all('dd')
            for i in range(min(len(dts), len(dds))):
                key = dts[i].get_text(strip=True)
                value = dds[i].get_text(strip=True)
                result["specifications"][key] = value
    
    # Check for items in set
    set_items_selectors = [
        '.product-single__set-items',
        '.set-items',
        '.product-set',
        '.package-contents',
        '.included-items'
    ]
    
    for selector in set_items_selectors:
        set_items_div = soup.select(selector)
        if set_items_div:
            print(f"Found set items with selector: {selector}")
            item_elements = set_items_div[0].select('.set-item, .item')
            for item in item_elements:
                item_name = item.select_one('.set-item__name, .item-name, .name')
                if item_name:
                    result["items_in_set"].append(item_name.get_text(strip=True))
            break
    
    # If still no description or specs, try a more general approach
    if not result["description"] and not result["specifications"]:
        # Look for any content in product information sections
        product_sections = soup.select('.product-info, .product-details, .product-information, .product-data')
        for section in product_sections:
            text = section.get_text(strip=True)
            if text and not result["description"]:
                result["description"] = text
    
    print(f"Parsing results: description: {bool(result['description'])}, " + 
          f"specs: {len(result['specifications'])}, " + 
          f"set items: {len(result['items_in_set'])}, " + 
          f"applications: {len(result['applications'])}")
    
    return result


def create_product_description(product_data, detailed_info):
    """
    Create a comprehensive product description in English based on:
    - Basic product data (name, code)
    - Detailed info extracted from the product page
    """
    # Product name and code for the title
    product_title = f"Wiha {product_data['code']} - {product_data['name']}"
    
    # Introduction paragraph - highlight benefits and use cases
    intro = f"The Wiha {product_data['code']} {product_data['name']} is a premium quality tool designed for professional use and demanding applications. "
    
    if detailed_info["description"]:
        # Add the official description, but clean it up a bit
        intro += detailed_info["description"]
    else:
        # Generic description if none is available
        intro += "Crafted with Wiha's renowned German engineering, this tool offers exceptional durability, precision, and ergonomic design to ensure comfort during extended use."
    
    # Main features section
    features = ["Features:"]
    
    # Extract key features from specifications
    if detailed_info["specifications"]:
        for key, value in detailed_info["specifications"].items():
            if key.lower() not in ["product code", "sku", "upc"]:  # Skip non-feature specs
                features.append(f"- {key}: {value}")
    
    # Generic features if none are found
    if len(features) <= 1:
        features.extend([
            "- Premium German engineering and construction",
            "- Ergonomic design for comfortable use",
            "- Made from high-quality materials for durability",
            f"- Part of Wiha's professional-grade tool lineup"
        ])
    
    # Applications section (if any found)
    applications = []
    if detailed_info["applications"]:
        applications.append("\nApplications:")
        for app in detailed_info["applications"]:
            applications.append(f"- {app}")
    
    # Set items section (if applicable)
    set_items = []
    if detailed_info["items_in_set"]:
        set_items.append("\nThis set includes:")
        for item in detailed_info["items_in_set"]:
            set_items.append(f"- {item}")
    
    # Additional information section
    additional_info = [
        "\nAdditional Information:",
        f"- Brand: Wiha",
        f"- Model: {product_data['code']}",
        "- Made in Germany",
        "- Professional-grade quality"
    ]
    
    # Closing statement - call to action and brand reinforcement
    closing = "\nWith Wiha's commitment to excellence and innovation, the " + \
              f"{product_data['name']} delivers the reliability and performance that professionals demand. " + \
              "Elevate your work with tools engineered to meet the highest standards."
    
    # Combine all sections
    sections = [
        product_title,
        "",
        intro,
        "",
        "\n".join(features),
        "\n".join(applications) if applications else "",
        "\n".join(set_items) if set_items else "",
        "\n".join(additional_info),
        "",
        closing
    ]
    
    return "\n".join(sections).replace("\n\n\n", "\n\n")


def translate_to_spanish(text, product_data, detailed_info):
    """
    Generate an effective Spanish product description using OpenAI API.
    
    Args:
        text: English description to translate
        product_data: Dictionary containing product information (code, name, etc.)
        detailed_info: Raw extracted information from the product page
    """
    if not OPENAI_API_KEY:
        return "API key not provided. Translation skipped."
    
    try:
        # Create a simplified structure with the key product information
        product_info = {
            "code": product_data.get('code', ''),
            "name": product_data.get('name', ''),
            "raw_description": detailed_info.get("description", ""),
            "specifications": detailed_info.get("specifications", {}),
            "items_in_set": detailed_info.get("items_in_set", [])
        }
        
        print(f"  Translation input - Product info: Code={product_info['code']}, Name={product_info['name']}")
        print(f"  Raw description length: {len(product_info['raw_description'])}")
        print(f"  Specifications count: {len(product_info['specifications'])}")
        
        # Check if product is a plier
        product_name_lower = product_data.get('name', '').lower()
        is_plier = any(term in product_name_lower for term in ['plier', 'pliers', 'alicate', 'pinza'])
        
        # Convert to JSON for the prompt
        product_json = json.dumps(product_info, indent=2)
        
        # Add information about product type to the prompt
        additional_instructions = ""
        if is_plier:
            additional_instructions = "NOTE: This product is a plier. Do not mention 'FABRICADO EN ALEMANIA' for this product type."
        
        prompt = f"""
        Create an effective Spanish product description for Mercado Libre based on the following Wiha tool information.
        Focus on ACCURACY first - make sure you correctly describe this specific product's features and uses.
        
        PRODUCT INFORMATION (JSON format):
        {product_json}
        
        ENGLISH DESCRIPTION (for reference):
        {text}
        
        {additional_instructions}
        
        Guidelines:
        1. START WITH THE PRODUCT NAME IN SPANISH. The original name is "{product_data.get('code', '')} {product_data.get('name', '')}" - translate this to Spanish and put it at the TOP of your response.
        2. Accurately describe THIS specific product - its exact features, specifications, and intended uses
        3. Highlight the practical benefits of THIS specific tool
        4. Include relevant application cases where this tool would be used
        5. If it's a set, clearly list the items included
        6. Maintain a professional marketing tone without exaggeration
        7. Keep technical measurements and specifications accurate
        8. OUTPUT MUST BE IN PLAIN TEXT format (no markdown, HTML, or other formatting)
        9. IMPORTANT: Convert any weight measurements from pounds (lb) to kilograms (kg). For example, "1.5 lb" should be converted to "0.68 kg".
        
        The description should be well-structured with:
        - Clear section titles (like "Características:", "Aplicaciones:", etc.)
        - Use simple dash or bullet symbol for lists
        - Plain text spacing for readability
        - No markdown, HTML, or special formatting characters
        - All weight measurements in kilograms (kg), not pounds (lb)
        """
        
        print(f"  Sending request to OpenAI API, model gpt-4o")
        
        # Create OpenAI client
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        
        try:
            # Updated API call with model
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a Spanish-speaking product content writer specializing in professional tools. Your job is to create accurate, effective product descriptions that properly represent each specific tool's features and applications."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=1500
            )
            
            # Get the translated text with Spanish product name at the top
            translated_text = response.choices[0].message.content.strip()
            
            print(f"  Successfully received translation, length: {len(translated_text)}")
            
            # Process text to ensure it's plain text
            plain_text = re.sub(r'#{1,6}\s+', '', translated_text)
            plain_text = re.sub(r'\*\*(.+?)\*\*', r'\1', plain_text)
            plain_text = re.sub(r'\*(.+?)\*', r'\1', plain_text)
            plain_text = re.sub(r'__(.+?)__', r'\1', plain_text)
            plain_text = re.sub(r'_(.+?)_', r'\1', plain_text)
            plain_text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', plain_text)
            
            # Conditionally add the "FABRICADO EN ALEMANIA" text if not a plier
            if not is_plier:
                fabrication_text = "\n-- FABRICADO EN ALEMANIA (no es producto chino) --\n\nSomos PROFITOOLS, el único representante oficial de Wiha en Argentina.\n\n"
                
                # Find the end of the first line (product name)
                first_line_end = plain_text.find('\n')
                if first_line_end != -1:
                    # Insert the fabrication text after the first line
                    plain_text = plain_text[:first_line_end+1] + fabrication_text + plain_text[first_line_end+1:]
                else:
                    # If no newline found, add it after the whole text
                    plain_text = plain_text + fabrication_text
            else:
                # For pliers, just add the PROFITOOLS line
                profitools_text = "\nSomos PROFITOOLS, el único representante oficial de Wiha en Argentina.\n\n"
                
                # Find the end of the first line (product name)
                first_line_end = plain_text.find('\n')
                if first_line_end != -1:
                    # Insert the text after the first line
                    plain_text = plain_text[:first_line_end+1] + profitools_text + plain_text[first_line_end+1:]
                else:
                    # If no newline found, add it after the whole text
                    plain_text = plain_text + profitools_text
            
            return plain_text
        
        except openai.OpenAIError as oe:
            print(f"  OpenAI API Error: {oe}")
            # Try to handle rate limits by waiting and retrying once
            if "rate limit" in str(oe).lower():
                print("  Rate limit hit. Waiting 20 seconds and retrying once...")
                time.sleep(20)
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": "You are a Spanish-speaking product content writer specializing in professional tools. Your job is to create accurate, effective product descriptions that properly represent each specific tool's features and applications."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.5,
                        max_tokens=1500
                    )
                    translated_text = response.choices[0].message.content.strip()
                    
                    # Rest of processing same as above
                    plain_text = re.sub(r'#{1,6}\s+', '', translated_text)
                    plain_text = re.sub(r'\*\*(.+?)\*\*', r'\1', plain_text)
                    plain_text = re.sub(r'\*(.+?)\*', r'\1', plain_text)
                    plain_text = re.sub(r'__(.+?)__', r'\1', plain_text)
                    plain_text = re.sub(r'_(.+?)_', r'\1', plain_text)
                    plain_text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', plain_text)
                    
                    # Add appropriate text
                    if not is_plier:
                        fabrication_text = "\n-- FABRICADO EN ALEMANIA (no es producto chino) --\n\nSomos PROFITOOLS, el único representante oficial de Wiha en Argentina.\n\n"
                        first_line_end = plain_text.find('\n')
                        if first_line_end != -1:
                            plain_text = plain_text[:first_line_end+1] + fabrication_text + plain_text[first_line_end+1:]
                        else:
                            plain_text = plain_text + fabrication_text
                    else:
                        profitools_text = "\nSomos PROFITOOLS, el único representante oficial de Wiha en Argentina.\n\n"
                        first_line_end = plain_text.find('\n')
                        if first_line_end != -1:
                            plain_text = plain_text[:first_line_end+1] + profitools_text + plain_text[first_line_end+1:]
                        else:
                            plain_text = plain_text + profitools_text
                    
                    return plain_text
                except Exception as e2:
                    return f"NOT FOUND - OpenAI API Error after retry: {str(e2)}"
            return f"NOT FOUND - OpenAI API Error: {str(oe)}"
        
    except Exception as e:
        print(f"  Error translating text: {e}")
        return f"NOT FOUND - Error in translation process: {str(e)}"


def parse_product_sitemap(xml_content):
    """Parse product sitemap XML and extract product information."""
    root = ElementTree.fromstring(xml_content)
    
    # Define namespace mapping
    namespaces = {
        'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9',
        'image': 'http://www.google.com/schemas/sitemap-image/1.1'
    }
    
    product_data = []
    
    # Process each URL in the sitemap
    for url_elem in root.findall('.//ns:url', namespaces):
        loc = url_elem.find('ns:loc', namespaces)
        if loc is not None and '/products/' in loc.text:
            # This is a product URL
            product_url = loc.text
            
            # Get the image URL if available
            image_loc = url_elem.find('.//image:loc', namespaces)
            image_url = image_loc.text if image_loc is not None else ""
            
            # Get image caption if available (often contains product code and name)
            image_caption = None
            caption_elem = url_elem.find('.//image:caption', namespaces)
            if caption_elem is not None and caption_elem.text:
                image_caption = caption_elem.text
            
            # Extract product code and name - first try from the full text content
            text_content = ''.join(url_elem.itertext())
            
            # Initialize variables
            product_code = None
            product_name = None
            
            # Try multiple extraction methods to increase chances of finding code
            
            # Method 1: Look for pattern "Wiha CODE PRODUCT_NAME" in caption
            if image_caption and 'Wiha ' in image_caption:
                parts = image_caption.split('Wiha ')
                if len(parts) > 1:
                    code_and_rest = parts[1].strip().split(' ', 1)
                    if len(code_and_rest) > 0:
                        product_code = code_and_rest[0].strip()
                    if len(code_and_rest) > 1:
                        product_name = code_and_rest[1].strip()
            
            # Method 2: If no code found yet, try from entire text content
            if not product_code and 'Wiha ' in text_content:
                parts = text_content.split('Wiha ')
                if len(parts) > 1:
                    code_and_rest = parts[1].strip().split(' ', 1)
                    if len(code_and_rest) > 0:
                        product_code = code_and_rest[0].strip()
                    if len(code_and_rest) > 1:
                        product_name = code_and_rest[1].strip()
            
            # Method 3: Try to extract code from the URL itself
            if not product_code:
                # Extract from URL pattern like /products/tool-name-12345
                url_parts = product_url.rstrip('/').split('/')
                if url_parts:
                    last_part = url_parts[-1]
                    # Look for numbers at the end of the URL
                    matches = re.findall(r'\d+$', last_part)
                    if matches:
                        product_code = matches[0]
                    else:
                        # Look for common patterns like product-name-12345
                        matches = re.findall(r'-(\d+)(?:-|$)', last_part)
                        if matches:
                            product_code = matches[0]
            
            # Method 4: Try to extract from product name pattern
            if not product_code and product_name:
                # Some product names end with the code in parentheses or after a dash
                matches = re.findall(r'[-(](\d+)[)-]', product_name)
                if matches:
                    product_code = matches[0]
            
            # If we found a product code, add it to our data
            if product_code:
                product_data.append({
                    'code': product_code,
                    'name': product_name or "Unknown Product Name",
                    'image_url': image_url,
                    'product_url': product_url
                })
            else:
                # If DEBUG is enabled, log products where we couldn't extract a code
                if DEBUG:
                    print(f"  Warning: Could not extract product code from URL: {product_url}")
    
    return product_data


def get_product_sitemaps(sitemap_url):
    """Get all product sitemap URLs from the main sitemap index."""
    xml_content = fetch_sitemap(sitemap_url)
    root = ElementTree.fromstring(xml_content)
    
    # Define namespace
    namespaces = {
        'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'
    }
    
    product_sitemaps = []
    
    # Look for sitemap URLs that contain "sitemap_products" in their name
    for sitemap_elem in root.findall('.//ns:sitemap', namespaces):
        loc = sitemap_elem.find('ns:loc', namespaces)
        if loc is not None and 'sitemap_products' in loc.text:
            product_sitemaps.append(loc.text)
    
    return product_sitemaps


def filter_products_by_code(product_data, product_codes):
    """Filter product data to only include products with specified codes."""
    if not product_codes:
        return product_data
    
    filtered_data = []
    for product in product_data:
        if product['code'] in product_codes:
            filtered_data.append(product)
    
    return filtered_data


def read_product_codes_csv(filename):
    """Read product codes from CSV file."""
    if not os.path.exists(filename):
        return []
    
    codes = []
    with open(filename, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            # Skip empty rows and comments
            if not row or row[0].startswith('#'):
                continue
            codes.append(row[0].strip())
    
    return codes


def create_empty_input_csv():
    """Create an empty input CSV file with headers."""
    with open(INPUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
        csvfile.write("ProductCode\n# Add your product codes below, one per line\n")


def write_product_data_csv(product_data, filename):
    """Write product data to CSV file."""
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'Product Code', 
            'Product Name', 
            'Image URL', 
            'Product URL', 
            'Spanish Description'  # Removed English Description column
        ])
        for product in product_data:
            writer.writerow([
                product.get('code', ''),
                product.get('name', ''),
                product.get('image_url', ''),
                product.get('product_url', ''),
                product.get('spanish_description', '')  # Only include Spanish description
            ])
    
    print(f"Product data written to {filename}")


def check_sitemap_products(sitemap_url, product_codes):
    """
    Quick check to test if the product codes can be found in the sitemap XML directly.
    This helps debug issues with product code extraction.
    """
    print("\nRunning sanity check on first sitemap...")
    
    try:
        # Get the first product sitemap
        if 'sitemap_products' in sitemap_url:
            first_sitemap_url = sitemap_url
        else:
            product_sitemaps = get_product_sitemaps(sitemap_url)
            if not product_sitemaps:
                print("  Warning: No product sitemaps found for sanity check")
                return
            first_sitemap_url = product_sitemaps[0]
        
        print(f"  Checking for product codes directly in XML of: {first_sitemap_url}")
        
        # Fetch the XML content
        xml_content = fetch_sitemap(first_sitemap_url)
        
        # Simple text search for each product code
        found_count = 0
        not_found = []
        
        for code in product_codes:
            if code in xml_content:
                found_count += 1
            else:
                not_found.append(code)
        
        print(f"  Direct XML search: Found {found_count} out of {len(product_codes)} product codes")
        
        if not_found and len(not_found) <= 10:
            print("  Codes not found in direct XML search:")
            for code in not_found:
                print(f"    - {code}")
        elif not_found:
            print(f"  {len(not_found)} codes were not found in direct XML search")
        
    except Exception as e:
        print(f"  Error during sanity check: {e}")


def main():
    # Basic URL validation
    try:
        parsed_url = urlparse(SITEMAP_URL)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError("Invalid URL format")
    except ValueError:
        print(f"Error: Invalid sitemap URL: {SITEMAP_URL}", file=sys.stderr)
        sys.exit(1)
    
    # Check if the input CSV file exists
    if not os.path.exists(INPUT_CSV):
        print(f"Input CSV file '{INPUT_CSV}' not found.")
        create_empty_input_csv()
        print("Please add product codes to the file and run the script again.")
        sys.exit(0)
    
    # Read product codes from the input CSV file
    product_codes = read_product_codes_csv(INPUT_CSV)
    if product_codes:
        print(f"Reading product codes from {INPUT_CSV}")
        print(f"Found {len(product_codes)} product codes in the CSV file")
        
        # Create a set for tracking which codes are actually found
        input_codes_set = set(product_codes)
        
        # Run a quick sanity check
        check_sitemap_products(SITEMAP_URL, product_codes)
    else:
        print(f"Warning: No valid product codes found in {INPUT_CSV}. Processing all products.")
        product_codes = None
        input_codes_set = set()
    
    print(f"Fetching sitemap from: {SITEMAP_URL}\n")
    
    # Check if the provided URL is already a product sitemap
    if 'sitemap_products' in SITEMAP_URL:
        product_sitemaps = [SITEMAP_URL]
    else:
        # Get product sitemap URLs
        product_sitemaps = get_product_sitemaps(SITEMAP_URL)
    
    if not product_sitemaps:
        print("Error: No product sitemaps found.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(product_sitemaps)} product sitemaps")
    
    all_product_data = []
    total_products = 0
    
    # Process each product sitemap
    for sitemap_url in product_sitemaps:
        print(f"Processing product sitemap: {sitemap_url}")
        xml_content = fetch_sitemap(sitemap_url)
        product_data = parse_product_sitemap(xml_content)
        total_products += len(product_data)
        all_product_data.extend(product_data)
        print(f"  Extracted {len(product_data)} products")
    
    # Filter products by code if necessary
    found_codes_set = set()
    if product_codes:
        filtered_data = []
        for product in all_product_data:
            if product['code'] in product_codes:
                filtered_data.append(product)
                found_codes_set.add(product['code'])
        
        # Find missing codes
        missing_codes = input_codes_set - found_codes_set
        
        print(f"\nFiltered to {len(filtered_data)} products matching your criteria")
        print(f"Found {len(found_codes_set)} out of {len(input_codes_set)} requested product codes")
        
        if missing_codes:
            print(f"\nWARNING: {len(missing_codes)} product codes from your input file were not found in the sitemap")
            
            # When in FORCE_MODE, add the missing codes as dummy products to process
            if FORCE_MODE and missing_codes:
                print(f"FORCE MODE enabled: Adding {len(missing_codes)} missing products with stub data")
                base_url = SITEMAP_URL.split('/sitemap')[0]
                
                for code in missing_codes:
                    dummy_product = {
                        'code': code,
                        'name': f"Product {code}",
                        'image_url': "",
                        'product_url': f"{base_url}/products/{code}"
                    }
                    filtered_data.append(dummy_product)
                
                print(f"Total products after adding missing codes: {len(filtered_data)}")
    else:
        filtered_data = all_product_data
    
    # Process each product page and generate descriptions
    enhanced_products = []
    processed_count = 0
    successful_count = 0
    failed_count = 0
    error_products = []
    
    # Apply product limit if set
    products_to_process = filtered_data
    if MAX_PRODUCTS > 0 and len(filtered_data) > MAX_PRODUCTS:
        products_to_process = filtered_data[:MAX_PRODUCTS]
        print(f"Limiting processing to {MAX_PRODUCTS} products as specified in .env")
    
    total_to_process = len(products_to_process)
    print(f"\nProcessing {total_to_process} product pages to generate descriptions...")
    
    for i, product in enumerate(products_to_process):
        try:
            print(f"\n----- Processing product {i+1}/{total_to_process}: {product['code']} - {product['name']} -----")
            
            # Fetch product page content
            html_content = fetch_product_page(product['product_url'])

            if not html_content:
                print(f"  Skipping product {product['code']} due to fetch error")
                # Instead of skipping, add it with error message
                enhanced_product = product.copy()
                enhanced_product['english_description'] = "NOT FOUND - Could not fetch product page"
                enhanced_product['spanish_description'] = "NOT FOUND - No se pudo obtener la página del producto"
                enhanced_product['detailed_info'] = {"description": "", "specifications": {}, "items_in_set": [], "applications": []}
                enhanced_products.append(enhanced_product)
                processed_count += 1
                failed_count += 1
                error_products.append(f"{product['code']} - {product['name']} (fetch error)")
                continue
            
            # Parse product page to extract detailed information
            detailed_info = parse_product_page(html_content)
            
            # Create English description
            english_description = create_product_description(product, detailed_info)
            
            # Translate to Spanish
            print(f"  Translating description for product {product['code']}")
            spanish_description = translate_to_spanish(english_description, product, detailed_info)
            
            # Check if there was an error in translation
            if spanish_description.startswith("NOT FOUND"):
                failed_count += 1
                error_products.append(f"{product['code']} - {product['name']} (translation error)")
            else:
                successful_count += 1
            
            # Add to enhanced products
            enhanced_product = product.copy()
            enhanced_product['english_description'] = english_description
            enhanced_product['spanish_description'] = spanish_description
            enhanced_product['detailed_info'] = detailed_info
            enhanced_products.append(enhanced_product)
            
            processed_count += 1
            
            # Add a small delay to avoid overloading the server and API
            time.sleep(1)
            
        except Exception as e:
            print(f"  Error processing product {product['code']}: {e}")
            # Add the product with error message instead of skipping it
            enhanced_product = product.copy()
            enhanced_product['english_description'] = f"ERROR - {str(e)}"
            enhanced_product['spanish_description'] = f"NOT FOUND - Error: {str(e)}"
            enhanced_product['detailed_info'] = {"description": "", "specifications": {}, "items_in_set": [], "applications": []}
            enhanced_products.append(enhanced_product)
            processed_count += 1
            failed_count += 1
            error_products.append(f"{product['code']} - {product['name']} (processing error: {str(e)[:50]}...)")
            continue
    
    # Write enhanced product data to CSV
    if enhanced_products:
        write_product_data_csv(enhanced_products, OUTPUT_CSV)
    
    # Print final summary
    print("\n========== PROCESSING SUMMARY ==========")
    print(f"Total products in sitemap(s): {total_products}")
    print(f"Products matching criteria: {len(filtered_data)}")
    print(f"Products processed: {processed_count}/{total_to_process}")
    print(f"Successfully processed: {successful_count}")
    print(f"Failed: {failed_count}")
    
    if failed_count > 0:
        print("\nFailed products:")
        for error_product in error_products:
            print(f"  - {error_product}")
    
    print(f"\nProduct data written to {OUTPUT_CSV}")
    print("=======================================")


if __name__ == "__main__":
    main() 