from pydantic import BaseModel, Field, ValidationError
from typing import List, Any, Dict, Type, Union

# --- KONTRAK SKEMA UNTUK GOOGLE SHEETS ---

class GoogleSheetsAppendRow(BaseModel):
    """
    Skema untuk menambahkan baris data baru ke Google Sheets.
    """
    spreadsheet_id: str = Field(
        ..., 
        description="ID unik spreadsheet yang ditemukan di URL browser (misal: '1abc123...')."
    )
    sheet_name: str = Field(
        default="Sheet1", 
        description="Nama tab/sheet spesifik di dalam file spreadsheet. Default adalah 'Sheet1'."
    )
    row_values: List[Union[str, int, float, bool, None]] = Field(
        ..., 
        description="Daftar nilai (array) yang akan dimasukkan ke dalam satu baris baru. Contoh: ['Data A', 100, True]."
    )

# --- REGISTRY TOOL ---
# Memetakan action_name ke class Pydantic yang sesuai
TOOL_REGISTRY: Dict[str, Type[BaseModel]] = {
    "append_row": GoogleSheetsAppendRow,
    # Di masa depan, tambahkan action lain di sini:
    # "create_spreadsheet": GoogleSheetsCreate,
}

def validate_tool_payload(action_name: str, raw_payload: dict) -> Dict[str, Any]:
    """
    Memvalidasi payload mentah dari AI terhadap skema Pydantic.
    
    Returns:
        Dict: Payload yang sudah tervalidasi jika sukses.
        
    Raises:
        ValueError: Jika action_name tidak terdaftar atau validasi gagal, 
                    mengembalikan pesan error yang diformat untuk Self-Correction AI.
    """
    schema_class = TOOL_REGISTRY.get(action_name)
    
    if not schema_class:
        raise ValueError(f"Action '{action_name}' tidak dikenali oleh sistem validasi.")

    try:
        # Melakukan validasi dan konversi tipe data otomatis
        validated_data = schema_class(**raw_payload)
        return validated_data.dict()
    
    except ValidationError as e:
        # Format error menjadi pesan yang informatif untuk Gemma (Self-Correction)
        error_messages = []
        for error in e.errors():
            field = " -> ".join([str(loc) for loc in error['loc']])
            message = error['msg']
            error_messages.append(f"Kesalahan pada parameter '{field}': {message}")
        
        # Gabungkan semua error menjadi satu string feedback
        feedback_to_ai = (
            f"Validasi gagal untuk action '{action_name}'. "
            f"Detail kesalahan: {'; '.join(error_messages)}. "
            "Mohon perbaiki parameter dan coba lagi."
        )
        raise ValueError(feedback_to_ai)

# --- CONTOH TESTING (UNIT TEST SEDERHANA) ---
if __name__ == "__main__":
    # Test Kasus Sukses
    test_payload = {
        "spreadsheet_id": "sheet_123",
        "sheet_name": "Sales_Data",
        "row_values": ["Produk A", 50000, False]
    }
    
    try:
        valid_data = validate_tool_payload("append_row", test_payload)
        print("Success:", valid_data)
    except ValueError as e:
        print("Failed:", e)

    # Test Kasus Gagal (row_values bukan list)
    bad_payload = {
        "spreadsheet_id": "sheet_123",
        "row_values": "bukan_list_tapi_string"
    }
    
    try:
        validate_tool_payload("append_row", bad_payload)
    except ValueError as e:
        print("\nExpected Error (Feedback for AI):")
        print(e)