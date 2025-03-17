# Sitemap URL Extractor and Product Description Generator

A Python utility that extracts product information from website sitemaps, generates detailed product descriptions, and translates them to Spanish for Mercado Libre listings.

## Features

- Fetch and parse XML sitemaps
- Extract product information from product pages
- Generate comprehensive product descriptions
- Translate descriptions to Spanish using OpenAI
- Export all data to CSV

## Requirements

- Python 3.6+
- Internet connection
- OpenAI API key (for translation)

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/sitemap-extractor.git
   cd sitemap-extractor
   ```

2. Install the required packages:
   ```
   pip3 install -r requirements.txt
   ```

3. Configure the `.env` file with your settings.

## Configuration

All configuration is done through the `.env` file:

```
# Sitemap URL to fetch
SITEMAP_URL=https://www.wihatools.com/sitemap.xml
# Input CSV file for product codes
INPUT_CSV=codes.csv
# Output CSV file for product data
OUTPUT_CSV=products.csv
# Process sitemaps recursively (true/false)
RECURSIVE=true
# OpenAI API Key for translation
OPENAI_API_KEY=your_api_key_here
# Maximum number of products to process (0 = all)
MAX_PRODUCTS=0
# Enable debugging output (true/false)
DEBUG=false
# Force process all codes from input CSV even if not found in sitemap (true/false)
FORCE_MODE=false
```

## Usage

Simply run the script without any arguments:

```
python3 sitemap_extractor.py
```

> **Note:** Make sure to use `python3` rather than just `python` to ensure the script runs with Python 3.

The script will:
1. Check if the input CSV file exists and create it if it doesn't
2. Read product codes from the input CSV file
3. Fetch and process the sitemap to find product URLs
4. Visit each product page to extract detailed information
5. Generate comprehensive product descriptions in English
6. Translate descriptions to Spanish using OpenAI
7. Save all product data to the output CSV file

## Input CSV Format

The input CSV file should contain product codes, one per line, in the first column:

```
ProductCode
# Add your product codes below, one per line
12345
67890
54321
```

Lines starting with `#` are treated as comments and ignored.

## Output CSV Format

The output CSV file contains the extracted product data with the following columns:

- Product Code
- Product Name
- Image URL
- Product URL
- Spanish Description

## Description Generation Process

The description generator:
1. Extracts basic product information from the sitemap
2. Fetches the full HTML content of each product page
3. Parses the HTML to extract:
   - Product description text
   - Technical specifications
   - Items included in sets (when applicable)
4. Creates a structured, comprehensive product description in English
5. Translates the description to Spanish using OpenAI's API
6. Saves the Spanish description to the output CSV

## Token Usage Optimization

The script optimizes OpenAI API token usage by:
- Creating concise, focused descriptions
- Limiting the number of products processed (configurable)
- Using the most efficient OpenAI model for translation

## Example Output

```
Reading product codes from codes.csv
Found 3 product codes in the CSV file
Fetching sitemap from: https://www.wihatools.com/sitemap.xml

Processing sitemap: https://www.wihatools.com/sitemap.xml
  https://www.wihatools.com/sitemap_products_1.xml
  Counting products in: https://www.wihatools.com/sitemap_products_1.xml
  Found 250 products in this sitemap
  Extracting product data from: https://www.wihatools.com/sitemap_products_1.xml
  Extracted data for 2 products
  https://www.wihatools.com/sitemap_products_2.xml
  Counting products in: https://www.wihatools.com/sitemap_products_2.xml
  Found 175 products in this sitemap
  Extracting product data from: https://www.wihatools.com/sitemap_products_2.xml
  Extracted data for 1 products
Total products across product sitemaps: 425

Product data written to products.csv

Found 4 URLs in the sitemap.
Found 425 total products.
Extracted data for 3 products matching your criteria.