import os
import csv
import json
import time
import tempfile
import re

from pathlib import Path
from urllib.parse import urlparse

import requests


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CHECKPOINT_FILE = BASE_DIR / "facebook_checkpoint.json"


# ============================================================
# FACEBOOK USER ACCESS TOKEN
# ============================================================

USER_ACCESS_TOKEN = "hadi blasa dial token"

GRAPH_VERSION = "v25.0"


# ============================================================
# WAIT SETTINGS
# ============================================================

# الوقت بين فيديو وفيديو بعد النشر الناجح
WAIT_SECONDS = 180

# عدد محاولات تحميل الفيديو
MAX_RETRIES = 3

# الوقت بين محاولات تحميل الفيديو
RETRY_WAIT = 30

# Timeout ديال تحميل الفيديو
DOWNLOAD_CONNECT_TIMEOUT = 15
DOWNLOAD_READ_TIMEOUT = 60


# ============================================================
# CHECKPOINT
# ============================================================

def load_checkpoint():

    if not CHECKPOINT_FILE.exists():

        return {
            "file_index": 0,
            "row_index": -1
        }

    try:

        with open(
            CHECKPOINT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return {
            "file_index": int(
                data.get(
                    "file_index",
                    0
                )
            ),

            "row_index": int(
                data.get(
                    "row_index",
                    -1
                )
            )
        }

    except Exception as e:

        print(
            "⚠️ Checkpoint error:",
            e
        )

        return {
            "file_index": 0,
            "row_index": -1
        }


def save_checkpoint(
    file_index,
    row_index,
    product_id=""
):

    data = {
        "file_index": file_index,
        "row_index": row_index,
        "last_product_id": product_id
    }

    temp_file = CHECKPOINT_FILE.with_suffix(
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(
        CHECKPOINT_FILE
    )

    print(
        f"💾 Checkpoint saved: "
        f"CSV {file_index + 1}, "
        f"row {row_index + 1}"
    )


# ============================================================
# CSV DISCOVERY
# ============================================================

def find_csv_files():

    files = []

    for path in BASE_DIR.glob("*.csv"):

        if path.is_file():

            files.append(path)

    files.sort(
        key=lambda p: p.name.lower()
    )

    return files


# ============================================================
# CSV ENCODING
# ============================================================

def detect_encoding(path):

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin1"
    ]

    for encoding in encodings:

        try:

            with open(
                path,
                "r",
                encoding=encoding,
                newline=""
            ) as f:

                f.read(4096)

            return encoding

        except UnicodeDecodeError:

            continue

    return "latin1"


# ============================================================
# CLEAN VALUE
# ============================================================

def clean_value(value):

    if value is None:

        return ""

    value = str(value).strip()

    match = re.search(
        r"\]\((https?://[^)]+)\)",
        value
    )

    if match:

        return match.group(1)

    value = value.strip("<>")

    return value.strip()


def extract_url(value):

    value = clean_value(value)

    if not value:

        return ""

    match = re.search(
        r"https?://[^\s\]\)>]+",
        value
    )

    if match:

        return match.group(0).rstrip(
            ".,;"
        )

    return value


# ============================================================
# HEADER NORMALIZATION
# ============================================================

def normalize_header(header):

    if header is None:

        return ""

    header = str(header)

    header = header.replace(
        "\ufeff",
        ""
    )

    header = header.replace(
        "\n",
        " "
    )

    header = header.strip()

    return re.sub(
        r"\s+",
        " ",
        header
    ).lower()


def find_column(
    fieldnames,
    wanted_names
):

    normalized = {}

    for field in fieldnames:

        normalized[
            normalize_header(field)
        ] = field

    for wanted in wanted_names:

        wanted_normalized = normalize_header(
            wanted
        )

        if wanted_normalized in normalized:

            return normalized[
                wanted_normalized
            ]

    return None


# ============================================================
# LOAD CSV
# ============================================================

def load_csv(path):

    encoding = detect_encoding(
        path
    )

    with open(
        path,
        "r",
        encoding=encoding,
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        if not reader.fieldnames:

            return [], {}

        fieldnames = reader.fieldnames

        columns = {

            "product_id": find_column(
                fieldnames,
                [
                    "ProductId",
                    "Product ID"
                ]
            ),

            "image_url": find_column(
                fieldnames,
                [
                    "Image Url",
                    "Image URL"
                ]
            ),

            "video_url": find_column(
                fieldnames,
                [
                    "Video Url",
                    "Video URL"
                ]
            ),

            "description": find_column(
                fieldnames,
                [
                    "Product Desc",
                    "Product Description",
                    "Description",
                    "Title"
                ]
            ),

            "origin_price": find_column(
                fieldnames,
                [
                    "Origin Price",
                    "Original Price"
                ]
            ),

            "discount_price": find_column(
                fieldnames,
                [
                    "Discount Price",
                    "Sale Price"
                ]
            ),

            "discount": find_column(
                fieldnames,
                [
                    "Discount"
                ]
            ),

            "currency": find_column(
                fieldnames,
                [
                    "Currency"
                ]
            ),

            "promotion_url": find_column(
                fieldnames,
                [
                    "Promotion Url",
                    "Promotion URL"
                ]
            ),

            "sales": find_column(
                fieldnames,
                [
                    "Sales180Day"
                ]
            ),

            "feedback": find_column(
                fieldnames,
                [
                    "Positive Feedback"
                ]
            )
        }

        rows = list(reader)

    return rows, columns


# ============================================================
# FACEBOOK GRAPH URL
# ============================================================

def graph_url(path):

    return (
        f"https://graph.facebook.com/"
        f"{GRAPH_VERSION}/{path}"
    )


# ============================================================
# GET FACEBOOK PAGES
# ============================================================

def get_pages():

    url = graph_url(
        "me/accounts"
    )

    params = {
        "access_token": USER_ACCESS_TOKEN,
        "fields": "id,name,access_token"
    }

    print()
    print(
        "⏳ جاري جلب Facebook Pages..."
    )

    response = requests.get(
        url,
        params=params,
        timeout=60
    )

    print(
        "Pages Status:",
        response.status_code
    )

    if not response.ok:

        print()
        print(
            "❌ Facebook Pages ERROR"
        )

        print(
            response.text
        )

        raise RuntimeError(
            "تعذر جلب Facebook Pages."
        )

    data = response.json()

    return data.get(
        "data",
        []
    )


# ============================================================
# CHOOSE PAGE
# ============================================================

def choose_page(pages):

    if not pages:

        print()
        print(
            "❌ ما لقا حتى Facebook Page."
        )

        raise SystemExit

    print()
    print("=" * 60)
    print(
        "FACEBOOK PAGES"
    )
    print("=" * 60)

    for i, page in enumerate(
        pages,
        start=1
    ):

        print(
            f"{i} - "
            f"{page.get('name')} "
            f"(ID: {page.get('id')})"
        )

    print()

    while True:

        try:

            choice = int(
                input(
                    "Choose page number: "
                )
            )

            if 1 <= choice <= len(pages):

                return pages[
                    choice - 1
                ]

            print(
                "❌ رقم غير صحيح."
            )

        except ValueError:

            print(
                "❌ خاصك تدخل رقم."
            )


# ============================================================
# TEST PAGE
# ============================================================

def test_page(
    page_id,
    page_access_token
):

    print()
    print(
        "Checking Facebook Page..."
    )

    print("=" * 60)

    url = graph_url(
        page_id
    )

    params = {
        "fields": "id,name",
        "access_token": page_access_token
    }

    response = requests.get(
        url,
        params=params,
        timeout=60
    )

    if not response.ok:

        print(
            "❌ Page check failed."
        )

        print(
            response.text
        )

        return False

    data = response.json()

    print(
        "✅ FACEBOOK PAGE"
    )

    print(
        "Name:",
        data.get(
            "name",
            "Unknown"
        )
    )

    print(
        "ID:",
        data.get(
            "id",
            page_id
        )
    )

    print("=" * 60)

    return True


# ============================================================
# CAPTION
# ============================================================

def make_caption(
    row,
    columns
):

    def value(name):

        column = columns.get(
            name
        )

        if not column:

            return ""

        return clean_value(
            row.get(
                column,
                ""
            )
        )

    title = value(
        "description"
    )

    origin_price = value(
        "origin_price"
    )

    discount_price = value(
        "discount_price"
    )

    discount = value(
        "discount"
    )

    currency = value(
        "currency"
    )

    promotion_url = extract_url(
        value(
            "promotion_url"
        )
    )

    sales = value(
        "sales"
    )

    feedback = value(
        "feedback"
    )

    if len(title) > 500:

        title = (
            title[:497]
            + "..."
        )

    lines = []

    # TITLE

    if title:

        lines.append(
            f"🔥 {title}"
        )

    # PRICE

    if discount_price:

        if currency:

            lines.append(
                f"💰 Price: "
                f"{discount_price} "
                f"{currency}"
            )

        else:

            lines.append(
                f"💰 Price: "
                f"{discount_price}"
            )

    # ORIGINAL PRICE

    if origin_price:

        lines.append(
            f"🏷️ Original: "
            f"{origin_price}"
        )

    # DISCOUNT

    if discount:

        lines.append(
            f"🔥 Discount: "
            f"{discount}"
        )

    # SALES

    if sales:

        lines.append(
            f"🛍️ Sold: {sales}"
        )

    # POSITIVE FEEDBACK

    if feedback:

        lines.append(
            f"⭐ Positive feedback: "
            f"{feedback}"
        )

    # BUY LINK

    if promotion_url:

        lines.append("")

        lines.append(
            "🛒 Buy here:"
        )

        lines.append(
            promotion_url
        )

    # HASHTAGS

    lines.append("")

    lines.append(
        "#AliExpress "
        "#AliExpressDeals "
        "#AliExpressFinds "
        "#Deals "
        "#BestDeals "
        "#Shopping "
        "#OnlineShopping "
        "#Temu"
    )

    return "\n".join(
        lines
    )


# ============================================================
# DOWNLOAD VIDEO
# ============================================================

def download_video(video_url):

    print()
    print(
        "Downloading video..."
    )

    parsed = urlparse(
        video_url
    )

    extension = ".mp4"

    if parsed.path.lower().endswith(
        ".mov"
    ):

        extension = ".mov"

    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=extension
    )

    temp_path = temp_file.name

    temp_file.close()

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            ),

            "Accept": "*/*",

            "Connection": "keep-alive"
        }

        with requests.get(
            video_url,
            stream=True,
            timeout=(
                DOWNLOAD_CONNECT_TIMEOUT,
                DOWNLOAD_READ_TIMEOUT
            ),
            headers=headers
        ) as response:

            # =================================================
            # 404
            # =================================================

            if response.status_code == 404:

                print()
                print(
                    "⚠️ VIDEO NOT AVAILABLE (404)"
                )

                print(
                    "➡️ Skipping this product."
                )

                try:

                    os.remove(
                        temp_path
                    )

                except Exception:

                    pass

                return None, "not_found"

            # =================================================
            # OTHER HTTP ERRORS
            # =================================================

            response.raise_for_status()

            total = 0

            with open(
                temp_path,
                "wb"
            ) as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:

                        f.write(
                            chunk
                        )

                        total += len(
                            chunk
                        )

        # =====================================================
        # EMPTY VIDEO
        # =====================================================

        if total == 0:

            print(
                "❌ Video file is empty."
            )

            try:

                os.remove(
                    temp_path
                )

            except Exception:

                pass

            return None, "empty"

        print(
            "Video downloaded:",
            f"{total / 1024 / 1024:.2f} MB"
        )

        return temp_path, "success"

    # =========================================================
    # TIMEOUT
    # =========================================================

    except requests.Timeout as e:

        print()
        print(
            "❌ VIDEO DOWNLOAD TIMEOUT"
        )

        print(
            e
        )

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

        return None, "timeout"

    # =========================================================
    # CONNECTION ERROR
    # =========================================================

    except requests.ConnectionError as e:

        print()
        print(
            "❌ VIDEO CONNECTION ERROR"
        )

        print(
            e
        )

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

        return None, "network"

    # =========================================================
    # HTTP ERROR
    # =========================================================

    except requests.HTTPError as e:

        print()
        print(
            "❌ HTTP ERROR"
        )

        print(
            e
        )

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

        return None, "http_error"

    # =========================================================
    # REQUEST ERROR
    # =========================================================

    except requests.RequestException as e:

        print()
        print(
            "❌ NETWORK ERROR"
        )

        print(
            e
        )

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

        return None, "network"

    # =========================================================
    # UNKNOWN ERROR
    # =========================================================

    except Exception as e:

        print()
        print(
            "❌ VIDEO DOWNLOAD ERROR"
        )

        print(
            e
        )

        try:

            os.remove(
                temp_path
            )

        except Exception:

            pass

        return None, "unknown"


# ============================================================
# UPLOAD VIDEO TO FACEBOOK
# ============================================================

def upload_video(
    page_id,
    page_access_token,
    video_path,
    caption
):

    url = graph_url(
        f"{page_id}/videos"
    )

    print()
    print(
        "Uploading video to Facebook..."
    )

    print(
        "Caption:"
    )

    print(
        "-" * 60
    )

    print(
        caption
    )

    print(
        "-" * 60
    )

    try:

        with open(
            video_path,
            "rb"
        ) as video_file:

            files = {

                "source": (
                    os.path.basename(
                        video_path
                    ),

                    video_file,

                    "video/mp4"
                )
            }

            data = {

                "description": caption,

                "access_token":
                    page_access_token
            }

            response = requests.post(
                url,
                files=files,
                data=data,
                timeout=900
            )

    except Exception as e:

        print()
        print(
            "❌ Upload request failed:"
        )

        print(
            e
        )

        return False, "network"

    # =========================================================
    # FACEBOOK ERROR
    # =========================================================

    if response.status_code != 200:

        print()
        print(
            "❌ FACEBOOK ERROR"
        )

        print(
            "HTTP:",
            response.status_code
        )

        print(
            response.text
        )

        error_text = response.text.lower()

        # =====================================================
        # PERMISSION
        # =====================================================

        if (
            "no permission" in error_text
            or "permission to publish" in error_text
            or "oauth" in error_text
            or "invalid oauth" in error_text
            or "access token" in error_text
        ):

            return False, "permission"

        # =====================================================
        # RATE LIMIT
        # =====================================================

        if (
            response.status_code == 429
            or "rate limit" in error_text
        ):

            return False, "rate_limit"

        return False, "temporary"

    # =========================================================
    # FACEBOOK SUCCESS
    # =========================================================

    try:

        result = response.json()

    except Exception:

        result = {}

    video_id = result.get(
        "id"
    )

    if not video_id:

        print(
            "❌ Facebook did not return video ID."
        )

        print(
            result
        )

        return False, "unknown"

    print()
    print("=" * 60)

    print(
        "✅ FACEBOOK VIDEO PUBLISHED"
    )

    print(
        "Video ID:",
        video_id
    )

    print("=" * 60)

    return True, video_id


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        "FACEBOOK ALIEXPRESS CSV "
        "VIDEO PUBLISHER"
    )

    print("=" * 60)


    # ========================================================
    # TOKEN
    # ========================================================

    if (
        not USER_ACCESS_TOKEN
        or USER_ACCESS_TOKEN
        == "hna fin kayan token"
    ):

        print()
        print(
            "❌ حط User Access Token "
            "ديالك فـUSER_ACCESS_TOKEN"
        )

        return


    # ========================================================
    # FIND CSV
    # ========================================================

    print()
    print(
        "Checking files..."
    )

    csv_files = find_csv_files()

    if not csv_files:

        print()
        print(
            "❌ No CSV files found."
        )

        print()
        print(
            "حط CSV files هنا:"
        )

        print(
            BASE_DIR
        )

        return


    print()
    print(
        "CSV FILES FOUND"
    )

    print("=" * 60)

    for i, path in enumerate(
        csv_files,
        start=1
    ):

        print(
            f"{i} - {path.name}"
        )

    print("=" * 60)

    print(
        f"Total CSV files: "
        f"{len(csv_files)}"
    )


    # ========================================================
    # FACEBOOK PAGES
    # ========================================================

    try:

        pages = get_pages()

    except Exception as e:

        print()
        print(
            "❌ Facebook error:"
        )

        print(
            e
        )

        return


    selected_page = choose_page(
        pages
    )

    page_id = selected_page.get(
        "id"
    )

    page_name = selected_page.get(
        "name"
    )

    page_access_token = selected_page.get(
        "access_token"
    )


    if not page_id:

        print(
            "❌ Page ID غير موجود."
        )

        return


    if not page_access_token:

        print()
        print(
            "❌ Meta ما رجعاتش "
            "Page Access Token."
        )

        print()
        print(
            "خاص User Token يكون عندو "
            "الصلاحيات المناسبة للـPage."
        )

        return


    print()

    print(
        f"✅ Page selected: "
        f"{page_name}"
    )

    print(
        f"✅ Page ID: "
        f"{page_id}"
    )


    # ========================================================
    # TEST PAGE
    # ========================================================

    if not test_page(
        page_id,
        page_access_token
    ):

        print()
        print(
            "🛑 STOPPED"
        )

        return


    # ========================================================
    # CHECKPOINT
    # ========================================================

    checkpoint = load_checkpoint()

    start_file_index = checkpoint[
        "file_index"
    ]

    start_row_index = checkpoint[
        "row_index"
    ]


    print()
    print("=" * 60)

    print(
        "CHECKPOINT"
    )

    print("=" * 60)

    print(
        f"Starting CSV: "
        f"{start_file_index + 1}/"
        f"{len(csv_files)}"
    )

    print(
        f"Starting row: "
        f"{start_row_index + 1}"
    )

    print("=" * 60)


    # ========================================================
    # ALL CSV FILES
    # ========================================================

    for file_index in range(
        start_file_index,
        len(csv_files)
    ):

        csv_path = csv_files[
            file_index
        ]


        print()
        print("=" * 60)

        print(
            f"CSV "
            f"{file_index + 1}/"
            f"{len(csv_files)}"
        )

        print(
            csv_path.name
        )

        print("=" * 60)


        try:

            rows, columns = load_csv(
                csv_path
            )

        except Exception as e:

            print()
            print(
                "❌ CSV reading error:"
            )

            print(
                e
            )

            continue


        if not rows:

            print(
                "⚠️ CSV is empty."
            )

            continue


        print(
            f"Products found: "
            f"{len(rows)}"
        )


        # ====================================================
        # CHECKPOINT START
        # ====================================================

        if (
            file_index
            == start_file_index
        ):

            row_start = (
                start_row_index + 1
            )

        else:

            row_start = 0


        # ====================================================
        # PRODUCTS
        # ====================================================

        for row_index in range(
            row_start,
            len(rows)
        ):

            row = rows[
                row_index
            ]


            # =================================================
            # VALUE HELPER
            # =================================================

            def value(name):

                column = columns.get(
                    name
                )

                if not column:

                    return ""

                return clean_value(
                    row.get(
                        column,
                        ""
                    )
                )


            product_id = value(
                "product_id"
            )

            description = value(
                "description"
            )

            video_url = extract_url(
                value(
                    "video_url"
                )
            )


            # =================================================
            # PRODUCT HEADER
            # =================================================

            print()
            print("=" * 60)

            print(
                f"PRODUCT "
                f"{row_index + 1}/"
                f"{len(rows)}"
            )

            print(
                f"CSV: "
                f"{file_index + 1}/"
                f"{len(csv_files)}"
            )

            print(
                "Product ID:",
                product_id
            )

            print(
                "Title:",
                description[:150]
            )

            print("=" * 60)


            # =================================================
            # NO VIDEO
            # =================================================

            if not video_url:

                print()
                print(
                    "⚠️ Video Url empty."
                )

                print(
                    "➡️ Skipping product."
                )

                save_checkpoint(
                    file_index,
                    row_index,
                    product_id
                )

                continue


            # =================================================
            # CAPTION
            # =================================================

            caption = make_caption(
                row,
                columns
            )


            # =================================================
            # DOWNLOAD + UPLOAD
            # =================================================

            published = False


            for attempt in range(
                1,
                MAX_RETRIES + 1
            ):

                temp_video = None


                try:

                    # =========================================
                    # DOWNLOAD
                    # =========================================

                    temp_video, download_status = download_video(
                        video_url
                    )


                    # =========================================
                    # 404
                    # =========================================

                    if download_status == "not_found":

                        print()
                        print(
                            "⏭️ PRODUCT SKIPPED"
                        )

                        print(
                            "Reason: "
                            "AliExpress video returned 404."
                        )


                        save_checkpoint(
                            file_index,
                            row_index,
                            product_id
                        )


                        published = "skipped"

                        break


                    # =========================================
                    # DOWNLOAD FAILED
                    # =========================================

                    if not temp_video:

                        print()

                        print(
                            f"❌ Download failed "
                            f"{attempt}/"
                            f"{MAX_RETRIES}"
                        )


                        # =====================================
                        # RETRY
                        # =====================================

                        if attempt < MAX_RETRIES:

                            print(
                                f"⏳ Waiting "
                                f"{RETRY_WAIT} "
                                f"seconds "
                                "before retry..."
                            )

                            time.sleep(
                                RETRY_WAIT
                            )

                            continue


                        # =====================================
                        # ALL RETRIES FAILED
                        # =====================================

                        print()
                        print("=" * 60)

                        print(
                            "⚠️ VIDEO DOWNLOAD FAILED"
                        )

                        print("=" * 60)

                        print(
                            "Product ID:",
                            product_id
                        )

                        print(
                            "➡️ Skipping this product."
                        )

                        print(
                            "➡️ Saving checkpoint..."
                        )


                        save_checkpoint(
                            file_index,
                            row_index,
                            product_id
                        )


                        published = "skipped"

                        break


                    # =========================================
                    # UPLOAD TO FACEBOOK
                    # =========================================

                    success, error_type = upload_video(
                        page_id,
                        page_access_token,
                        temp_video,
                        caption
                    )


                    # =========================================
                    # SUCCESS
                    # =========================================

                    if success:

                        published = True

                        break


                    # =========================================
                    # PERMISSION ERROR
                    # =========================================

                    if error_type == "permission":

                        print()
                        print(
                            "🛑 FACEBOOK "
                            "PERMISSION ERROR"
                        )

                        print()

                        print(
                            "خاصنا نصلحو "
                            "صلاحيات Facebook/Meta."
                        )

                        return


                    # =========================================
                    # RATE LIMIT
                    # =========================================

                    if error_type == "rate_limit":

                        wait_time = (
                            60 * attempt
                        )

                        print()

                        print(
                            "⚠️ Rate limit."
                        )

                        print(
                            f"Waiting "
                            f"{wait_time} "
                            f"seconds..."
                        )

                        time.sleep(
                            wait_time
                        )


                    elif attempt < MAX_RETRIES:

                        print()

                        print(
                            f"⏳ Waiting "
                            f"{RETRY_WAIT} "
                            f"seconds..."
                        )

                        time.sleep(
                            RETRY_WAIT
                        )


                except requests.RequestException as e:

                    print()

                    print(
                        f"❌ NETWORK ERROR "
                        f"{attempt}/"
                        f"{MAX_RETRIES}"
                    )

                    print(
                        e
                    )


                    if attempt < MAX_RETRIES:

                        print(
                            f"⏳ Waiting "
                            f"{RETRY_WAIT} "
                            f"seconds..."
                        )

                        time.sleep(
                            RETRY_WAIT
                        )


                except Exception as e:

                    print()

                    print(
                        f"❌ ERROR "
                        f"{attempt}/"
                        f"{MAX_RETRIES}"
                    )

                    print(
                        e
                    )


                    if attempt < MAX_RETRIES:

                        time.sleep(
                            RETRY_WAIT
                        )


                finally:

                    # =========================================
                    # DELETE TEMP VIDEO
                    # =========================================

                    if temp_video:

                        try:

                            os.remove(
                                temp_video
                            )

                            print(
                                "Temporary "
                                "video deleted."
                            )

                        except Exception:

                            pass


            # =================================================
            # SKIPPED PRODUCT
            # =================================================

            if published == "skipped":

                print()
                print(
                    "➡️ Moving to next product..."
                )

                continue


            # =================================================
            # SUCCESS
            # =================================================

            if published:

                print()
                print(
                    "✅ Product completed."
                )


                save_checkpoint(
                    file_index,
                    row_index,
                    product_id
                )


                # =============================================
                # LAST PRODUCT
                # =============================================

                if (
                    file_index
                    == len(csv_files) - 1
                    and
                    row_index
                    == len(rows) - 1
                ):

                    print()
                    print("=" * 60)

                    print(
                        "🎉 ALL CSV FILES "
                        "COMPLETED"
                    )

                    print("=" * 60)

                    return


                # =============================================
                # WAIT
                # =============================================

                print()

                print(
                    f"⏳ Waiting "
                    f"{WAIT_SECONDS} seconds "
                    "before next product..."
                )


                for remaining in range(
                    WAIT_SECONDS,
                    0,
                    -1
                ):

                    if (
                        remaining
                        == WAIT_SECONDS
                        or remaining % 30 == 0
                        or remaining <= 5
                    ):

                        print(
                            f"Next product "
                            f"in {remaining} "
                            f"seconds..."
                        )

                    time.sleep(1)


            # =================================================
            # FAILURE
            # =================================================

            else:

                print()
                print("=" * 60)

                print(
                    "🛑 STOPPED"
                )

                print(
                    "Product was NOT completed."
                )

                print(
                    "Run the program again "
                    "to retry this product."
                )

                print("=" * 60)

                return


        # ====================================================
        # CSV COMPLETED
        # ====================================================

        save_checkpoint(
            file_index + 1,
            -1,
            ""
        )


        print()
        print("=" * 60)

        print(
            f"✅ CSV COMPLETED: "
            f"{csv_path.name}"
        )

        print("=" * 60)


    # ========================================================
    # EVERYTHING COMPLETED
    # ========================================================

    print()
    print("=" * 60)

    print(
        "🎉 ALL CSV FILES COMPLETED"
    )

    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()