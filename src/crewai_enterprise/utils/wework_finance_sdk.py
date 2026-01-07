import ctypes
import os
import logging
import platform

logger = logging.getLogger(__name__)

# Define C structs
class Slice_t(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_char_p),
        ("len", ctypes.c_int),
    ]

class MediaData_t(ctypes.Structure):
    _fields_ = [
        ("outindexbuf", ctypes.c_char_p),
        ("out_len", ctypes.c_int),
        ("data", ctypes.c_char_p),
        ("data_len", ctypes.c_int),
        ("is_finish", ctypes.c_int),
    ]

class WeWorkFinanceSDK:
    """Python wrapper for libWeWorkFinanceSdk_C.so using ctypes."""

    def __init__(self, lib_path: str = None):
        if lib_path is None:
            # Default to location in company_docs
            lib_path = os.getenv("WECOM_FINANCE_SDK_LIB", "/opt/wecom-callback/company_docs/C_sdk/libWeWorkFinanceSdk_C.so")
        
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"WeCom Finance SDK library not found at: {lib_path}")

        try:
            self.lib = ctypes.CDLL(lib_path)
            self._setup_functions()
            self.sdk = None
            logger.info(f"Successfully loaded WeCom Finance SDK from {lib_path}")
        except Exception as e:
            logger.error(f"Failed to load WeCom Finance SDK: {e}")
            raise

    def _setup_functions(self):
        # void* NewSdk()
        self.lib.NewSdk.restype = ctypes.c_void_p
        self.lib.NewSdk.argtypes = []

        # int Init(void* sdk, const char* corpid, const char* secret)
        self.lib.Init.restype = ctypes.c_int
        self.lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]

        # int GetChatData(void* sdk, unsigned long long seq, unsigned int limit, const char* proxy, const char* passwd, int timeout, Slice_t* chatData)
        self.lib.GetChatData.restype = ctypes.c_int
        self.lib.GetChatData.argtypes = [
            ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_uint, 
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, 
            ctypes.POINTER(Slice_t)
        ]

        # int DecryptData(const char* encrypt_key, const char* encrypt_msg, Slice_t* msg)
        self.lib.DecryptData.restype = ctypes.c_int
        self.lib.DecryptData.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(Slice_t)]

        # int GetMediaData(void* sdk, const char* indexbuf, const char* sdkFileid, const char* proxy, const char* passwd, int timeout, MediaData_t* mediaData)
        self.lib.GetMediaData.restype = ctypes.c_int
        self.lib.GetMediaData.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
            ctypes.POINTER(MediaData_t)
        ]

        # void FreeSlice(Slice_t* slice)
        self.lib.FreeSlice.restype = None
        self.lib.FreeSlice.argtypes = [ctypes.POINTER(Slice_t)]

        # void FreeMediaData(MediaData_t* mediaData)
        self.lib.FreeMediaData.restype = None
        self.lib.FreeMediaData.argtypes = [ctypes.POINTER(MediaData_t)]

        # void DestroySdk(void* sdk)
        self.lib.DestroySdk.restype = None
        self.lib.DestroySdk.argtypes = [ctypes.c_void_p]

    def init(self, corp_id: str, secret: str) -> bool:
        """Initialize the SDK with credentials."""
        self.sdk = self.lib.NewSdk()
        if not self.sdk:
            logger.error("Failed to create SDK instance")
            return False
        
        ret = self.lib.Init(self.sdk, corp_id.encode(), secret.encode())
        if ret != 0:
            logger.error(f"Failed to initialize SDK with CorpID/Secret: ret={ret}")
            return False
        
        return True

    def decrypt_data(self, encrypt_key: str, encrypt_msg: str) -> str:
        """Decrypt chat message data using the provided (decrypted) random key."""
        slice_out = Slice_t()
        ret = self.lib.DecryptData(encrypt_key.encode(), encrypt_msg.encode(), ctypes.byref(slice_out))
        
        if ret != 0:
            logger.error(f"Failed to decrypt message data: ret={ret}")
            return None
        
        try:
            result = slice_out.buf[:slice_out.len].decode('utf-8')
            return result
        finally:
            self.lib.FreeSlice(ctypes.byref(slice_out))

    def get_chat_data(self, seq: int, limit: int = 100, timeout: int = 30) -> list[dict]:
        """Fetch chat messages starting from seq+1."""
        if not self.sdk:
            raise RuntimeError("SDK not initialized. Call init() first.")
            
        slice_out = Slice_t()
        import json
        
        ret = self.lib.GetChatData(
            self.sdk, seq, limit, 
            None, None, timeout, ctypes.byref(slice_out)
        )
        
        if ret != 0:
            logger.error(f"Failed to get chat data: ret={ret}")
            return None
            
        try:
            # Check if slice_out.buf is None or slice_out.len is 0
            if not slice_out.buf or slice_out.len == 0:
                return []
                
            raw_data = slice_out.buf[:slice_out.len].decode('utf-8')
            data = json.loads(raw_data)
            return data.get("chatdata", [])
        except Exception as e:
            logger.error(f"Failed to parse chat data JSON: {e}")
            return None
        finally:
            self.lib.FreeSlice(ctypes.byref(slice_out))

    def get_media_data(self, sdk_file_id: str, timeout: int = 30) -> bytes:
        """Download complete media data (file content) using sdk_file_id."""
        if not self.sdk:
            raise RuntimeError("SDK not initialized. Call init() first.")

        index_buf = b""
        full_data = b""
        
        while True:
            media_out = MediaData_t()
            media_out.outindexbuf = None
            media_out.data = None
            
            ret = self.lib.GetMediaData(
                self.sdk, index_buf, sdk_file_id.encode(), 
                None, None, timeout, ctypes.byref(media_out)
            )
            
            if ret != 0:
                logger.error(f"Failed to get media data for {sdk_file_id}: ret={ret}")
                break
                
            if media_out.data and media_out.data_len > 0:
                full_data += media_out.data[:media_out.data_len]
            
            index_buf = media_out.outindexbuf[:media_out.out_len]
            is_finish = media_out.is_finish
            
            self.lib.FreeMediaData(ctypes.byref(media_out))
            
            if is_finish:
                break
        
        return full_data

    def __del__(self):
        if hasattr(self, 'sdk') and self.sdk:
            self.lib.DestroySdk(self.sdk)
