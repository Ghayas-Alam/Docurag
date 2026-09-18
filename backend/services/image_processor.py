import os
import sys
import pymupdf


# ==========================================
# PROJECT PATHS
# ==========================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

BACKEND_ROOT = os.path.join(
    PROJECT_ROOT,
    "backend"
)

sys.path.append(PROJECT_ROOT)
sys.path.append(BACKEND_ROOT)


from database.database import get_db_connection


# ==========================================
# IMAGE STORAGE
# ==========================================

IMAGE_FOLDER = os.path.join(
    PROJECT_ROOT,
    "extracted_images"
)


# ==========================================
# EXTRACT IMAGES FROM PDF
# ==========================================

def extract_images_from_pdf(document_id):

    connection = get_db_connection()

    try:

        # ----------------------------------
        # Get document information
        # ----------------------------------

        document = connection.execute(
            """
            SELECT
                id,
                file_path,
                file_type,
                original_filename
            FROM documents
            WHERE id = ?
            """,
            (document_id,)
        ).fetchone()

        if not document:

            raise Exception(
                "Document not found"
            )

        if document["file_type"] != "pdf":

            raise Exception(
                "Only PDF documents are supported"
            )

        file_path = document["file_path"]

        if not os.path.exists(file_path):

            raise Exception(
                "PDF file not found"
            )

        # ----------------------------------
        # Create document image folder
        # ----------------------------------

        document_image_folder = os.path.join(
            IMAGE_FOLDER,
            str(document_id)
        )

        os.makedirs(
            document_image_folder,
            exist_ok=True
        )

        # ----------------------------------
        # Remove previous image records
        # ----------------------------------

        connection.execute(
            """
            DELETE FROM image_analysis
            WHERE document_id = ?
            """,
            (document_id,)
        )

        connection.commit()

        # ----------------------------------
        # Open PDF
        # ----------------------------------

        pdf = pymupdf.open(
            file_path
        )

        total_images = 0

        pages_with_images = set()

        # ----------------------------------
        # Process every page
        # ----------------------------------

        for page_number, page in enumerate(
            pdf,
            start=1
        ):

            images = page.get_images(
                full=True
            )

            if not images:
                continue

            pages_with_images.add(
                page_number
            )

            # ----------------------------------
            # Extract every image
            # ----------------------------------

            for image_index, image_info in enumerate(
                images,
                start=1
            ):

                xref = image_info[0]

                try:

                    image_data = pdf.extract_image(
                        xref
                    )

                except Exception:

                    continue

                image_bytes = image_data[
                    "image"
                ]

                image_extension = image_data[
                    "ext"
                ]

                total_images += 1

                image_filename = (
                    f"page_{page_number}_"
                    f"image_{image_index}."
                    f"{image_extension}"
                )

                image_path = os.path.join(
                    document_image_folder,
                    image_filename
                )

                # ----------------------------------
                # Save image
                # ----------------------------------

                with open(
                    image_path,
                    "wb"
                ) as image_file:

                    image_file.write(
                        image_bytes
                    )

                # ----------------------------------
                # Save image metadata
                # ----------------------------------

                connection.execute(
                    """
                    INSERT INTO image_analysis
                    (
                        document_id,
                        page_number,
                        image_index,
                        image_path,
                        image_type
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        page_number,
                        image_index,
                        image_path,
                        image_extension
                    )
                )

        # ----------------------------------
        # Close PDF
        # ----------------------------------

        pdf.close()

        connection.commit()

        return {
            "document_id": document_id,
            "pages_with_images": len(
                pages_with_images
            ),
            "total_images": total_images,
            "status": "success"
        }

    except Exception as error:

        connection.rollback()

        raise error

    finally:

        connection.close()


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print(
        "\n================================"
    )

    print(
        "DOCURAG IMAGE EXTRACTION TEST"
    )

    print(
        "================================"
    )

    # Test with TCS document
    document_id = 1

    print(
        f"\nProcessing Document ID: "
        f"{document_id}"
    )

    try:

        result = extract_images_from_pdf(
            document_id
        )

        print(
            "\nImage extraction completed!"
        )

        print(
            f"Document ID: "
            f"{result['document_id']}"
        )

        print(
            f"Pages with images: "
            f"{result['pages_with_images']}"
        )

        print(
            f"Total images: "
            f"{result['total_images']}"
        )

        print(
            f"Status: "
            f"{result['status']}"
        )

    except Exception as error:

        print(
            "\nImage extraction failed:"
        )

        print(
            str(error)
        )