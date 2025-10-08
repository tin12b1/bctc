import streamlit as st
import pandas as pd
from google import genai
from google.genai.errors import APIError

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Phân Tích Báo cáo Tài Chính",
    layout="wide"
)

st.title("Ứng dụng Phân Tích Báo Cáo Tài Chính & Chat AI 📊")

# --- 1. Khởi tạo Lịch sử Chat trong Session State ---
# Đảm bảo giữ ngữ cảnh hội thoại giữa các lần tương tác
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = [
        {
            "role": "model",
            "content": "Chào bạn! Tôi là Gemini, một chuyên gia phân tích tài chính. Hãy tải lên file Excel để bắt đầu phân tích. Sau khi có kết quả, bạn có thể hỏi tôi bất kỳ câu hỏi nào về báo cáo tài chính này hoặc thị trường chung."
        }
    ]

# --- Hàm tính toán chính (Sử dụng Caching để Tối ưu hiệu suất) ---
@st.cache_data
def process_financial_data(df):
    """Thực hiện các phép tính Tăng trưởng và Tỷ trọng."""
    
    # Đảm bảo các giá trị là số để tính toán
    numeric_cols = ['Năm trước', 'Năm sau']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 1. Tính Tốc độ Tăng trưởng
    # Dùng .replace(0, 1e-9) cho Series Pandas để tránh lỗi chia cho 0
    df['Tốc độ tăng trưởng (%)'] = (
        (df['Năm sau'] - df['Năm trước']) / df['Năm trước'].replace(0, 1e-9)
    ) * 100

    # 2. Tính Tỷ trọng theo Tổng Tài sản
    # Lọc chỉ tiêu "TỔNG CỘNG TÀI SẢN"
    tong_tai_san_row = df[df['Chỉ tiêu'].str.contains('TỔNG CỘNG TÀI SẢN', case=False, na=False)]
    
    if tong_tai_san_row.empty:
        raise ValueError("Không tìm thấy chỉ tiêu 'TỔNG CỘNG TÀI SẢN'.")

    tong_tai_san_N_1 = tong_tai_san_row['Năm trước'].iloc[0]
    tong_tai_san_N = tong_tai_san_row['Năm sau'].iloc[0]

    # Xử lý giá trị 0 cho mẫu số
    divisor_N_1 = tong_tai_san_N_1 if tong_tai_san_N_1 != 0 else 1e-9
    divisor_N = tong_tai_san_N if tong_tai_san_N != 0 else 1e-9

    # Tính tỷ trọng với mẫu số đã được xử lý
    df['Tỷ trọng Năm trước (%)'] = (df['Năm trước'] / divisor_N_1) * 100
    df['Tỷ trọng Năm sau (%)'] = (df['Năm sau'] / divisor_N) * 100
    
    return df

# --- Hàm gọi API Gemini để phân tích báo cáo ---
def get_ai_analysis(data_for_ai, api_key):
    """Gửi dữ liệu phân tích đến Gemini API và nhận nhận xét."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'
        
        prompt = f"""
        Bạn là một chuyên gia phân tích tài chính chuyên nghiệp. Dựa trên các chỉ số tài chính sau, hãy đưa ra một nhận xét khách quan, ngắn gọn (khoảng 3-4 đoạn) về tình hình tài chính của doanh nghiệp. Đánh giá tập trung vào tốc độ tăng trưởng, thay đổi cơ cấu tài sản và khả năng thanh toán hiện hành.
        
        Dữ liệu thô và chỉ số:
        {data_for_ai}
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết lỗi: {e}"
    except KeyError:
        return "Lỗi: Không tìm thấy Khóa API 'GEMINI_API_KEY'. Vui lòng kiểm tra cấu hình Secrets trên Streamlit Cloud."
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"

# --- Hàm Chat Tương tác (ĐÃ SỬA LỖI INVALID_ARGUMENT) ---
def get_chat_response(messages, api_key):
    """Gửi toàn bộ lịch sử chat và nhận phản hồi mới từ Gemini (có duy trì ngữ cảnh)."""
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'
        
        # Hướng dẫn hệ thống (System instruction)
        system_instruction = "Bạn là một chuyên gia phân tích tài chính hữu ích và thân thiện. Trả lời các câu hỏi về tài chính, kinh tế, hoặc dữ liệu được cung cấp (nếu có). Giữ câu trả lời ngắn gọn và tập trung."
        
        # CHÚ Ý SỬA LỖI: Cấu trúc lại tin nhắn để đảm bảo role hợp lệ (user, model)
        # Chúng ta sẽ chèn hướng dẫn hệ thống vào tin nhắn đầu tiên của người dùng
        
        # Chuyển đổi lịch sử chat từ Streamlit format sang Gemini format
        # Đồng thời thay đổi role 'assistant' (mặc định của Streamlit) thành 'model' (của Gemini)
        contents = []
        for i, m in enumerate(messages):
            role = 'model' if m['role'] == 'model' or m['role'] == 'assistant' else 'user'
            content = m["content"]
            
            # Nếu đây là tin nhắn đầu tiên của người dùng, chèn system instruction vào nội dung
            if i == 1 and role == 'user': # Giả định tin nhắn đầu tiên (i=0) là của model chào hỏi
                content = f"HƯỚNG DẪN: {system_instruction}\n\n[QUERY] {content}"
            
            contents.append({
                "role": role, 
                "parts": [{"text": content}]
            })
            
        # Loại bỏ tin nhắn chào hỏi ban đầu (i=0) của model nếu đã chèn instruction vào user query
        # Ta chỉ cần tin nhắn từ người dùng và phản hồi tiếp theo.
        # Tuy nhiên, để giữ ngữ cảnh, ta cần xử lý tin nhắn đầu tiên (i=0) là tin nhắn chào hỏi của model
        # Chỉ loại bỏ role='system' gây lỗi. Role 'model' và 'user' là hợp lệ.
        
        response = client.models.generate_content(
            model=model_name,
            contents=contents
        )
        return response.text
    except APIError as e:
        # Lỗi Invalid Argument (400) thường xảy ra do role không hợp lệ hoặc cấu trúc parts sai
        if 'INVALID_ARGUMENT' in str(e):
             return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc cấu trúc tin nhắn. Chi tiết lỗi: {e}. Vấn đề thường do role không hợp lệ (cần là 'user' hoặc 'model')."
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định trong Chat: {e}"


# --- Chức năng 1: Tải File ---
uploaded_file = st.file_uploader(
    "1. Tải file Excel Báo cáo Tài chính (Chỉ tiêu | Năm trước | Năm sau)",
    type=['xlsx', 'xls']
)

if uploaded_file is not None:
    try:
        df_raw = pd.read_excel(uploaded_file)
        
        # Tiền xử lý: Đảm bảo chỉ có 3 cột quan trọng
        df_raw.columns = ['Chỉ tiêu', 'Năm trước', 'Năm sau']
        
        # Xử lý dữ liệu
        df_processed = process_financial_data(df_raw.copy())

        if df_processed is not None:
            
            # --- Chức năng 2 & 3: Hiển thị Kết quả ---
            st.subheader("2. Tốc độ Tăng trưởng & 3. Tỷ trọng Cơ cấu Tài sản")
            st.dataframe(df_processed.style.format({
                'Năm trước': '{:,.0f}',
                'Năm sau': '{:,.0f}',
                'Tốc độ tăng trưởng (%)': '{:.2f}%',
                'Tỷ trọng Năm trước (%)': '{:.2f}%',
                'Tỷ trọng Năm sau (%)': '{:.2f}%'
            }), use_container_width=True)
            
            # --- Chức năng 4: Tính Chỉ số Tài chính ---
            st.subheader("4. Các Chỉ số Tài chính Cơ bản")
            
            # Khởi tạo giá trị mặc định cho chỉ số thanh toán
            thanh_toan_hien_hanh_N = "N/A"
            thanh_toan_hien_hanh_N_1 = "N/A"
            
            try:
                # Lấy Tài sản ngắn hạn
                tsnh_n = df_processed[df_processed['Chỉ tiêu'].str.contains('TÀI SẢN NGẮN HẠN', case=False, na=False)]['Năm sau'].iloc[0]
                tsnh_n_1 = df_processed[df_processed['Chỉ tiêu'].str.contains('TÀI SẢN NGẮN HẠN', case=False, na=False)]['Năm trước'].iloc[0]

                # Lấy Nợ ngắn hạn
                no_ngan_han_N = df_processed[df_processed['Chỉ tiêu'].str.contains('NỢ NGẮN HẠN', case=False, na=False)]['Năm sau'].iloc[0]  
                no_ngan_han_N_1 = df_processed[df_processed['Chỉ tiêu'].str.contains('NỢ NGẮN HẠN', case=False, na=False)]['Năm trước'].iloc[0]

                # Tính toán, kiểm tra chia cho 0
                if no_ngan_han_N != 0:
                     thanh_toan_hien_hanh_N = tsnh_n / no_ngan_han_N
                
                if no_ngan_han_N_1 != 0:
                    thanh_toan_hien_hanh_N_1 = tsnh_n_1 / no_ngan_han_N_1
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric(
                        label="Chỉ số Thanh toán Hiện hành (Năm trước)",
                        value=f"{thanh_toan_hien_hanh_N_1:.2f} lần" if isinstance(thanh_toan_hien_hanh_N_1, (int, float)) else "N/A"
                    )
                with col2:
                    if isinstance(thanh_toan_hien_hanh_N, (int, float)) and isinstance(thanh_toan_hien_hanh_N_1, (int, float)):
                        st.metric(
                            label="Chỉ số Thanh toán Hiện hành (Năm sau)",
                            value=f"{thanh_toan_hien_hanh_N:.2f} lần",
                            delta=f"{thanh_toan_hien_hanh_N - thanh_toan_hien_hanh_N_1:.2f}"
                        )
                    else:
                        st.metric(
                            label="Chỉ số Thanh toán Hiện hành (Năm sau)",
                            value="N/A"
                        )
                    
            except IndexError:
                 st.warning("Thiếu chỉ tiêu 'TÀI SẢN NGẮN HẠN' hoặc 'NỢ NGẮN HẠN' để tính chỉ số.")
            except ZeroDivisionError:
                st.warning("Không thể tính chỉ số thanh toán hiện hành do Nợ ngắn hạn bằng 0.")

            
            # --- Chức năng 5: Nhận xét AI (Analysis) ---
            st.subheader("5. Nhận xét Tình hình Tài chính (AI)")
            
            # Chuẩn bị dữ liệu để gửi cho AI (đảm bảo chỉ số thanh toán là string nếu là N/A)
            val_n_1 = f"{thanh_toan_hien_hanh_N_1:.2f}" if isinstance(thanh_toan_hien_hanh_N_1, (int, float)) else str(thanh_toan_hien_hanh_N_1)
            val_n = f"{thanh_toan_hien_hanh_N:.2f}" if isinstance(thanh_toan_hien_hanh_N, (int, float)) else str(thanh_toan_hien_hanh_N)
            
            data_for_ai = pd.DataFrame({
                'Chỉ tiêu': [
                    'Toàn bộ Bảng phân tích (dữ liệu thô)', 
                    'Tăng trưởng Tài sản ngắn hạn (%)', 
                    'Thanh toán hiện hành (N-1)', 
                    'Thanh toán hiện hành (N)'
                ],
                'Giá trị': [
                    df_processed.to_markdown(index=False),
                    f"{df_processed[df_processed['Chỉ tiêu'].str.contains('TÀI SẢN NGẮN HẠN', case=False, na=False)]['Tốc độ tăng trưởng (%)'].iloc[0]:.2f}%" if not df_processed[df_processed['Chỉ tiêu'].str.contains('TÀI SẢN NGẮN HẠN', case=False, na=False)].empty else "N/A", 
                    val_n_1, 
                    val_n
                ]
            }).to_markdown(index=False) 

            if st.button("Yêu cầu AI Phân tích"):
                api_key = st.secrets.get("GEMINI_API_KEY") 
                
                if api_key:
                    with st.spinner('Đang gửi dữ liệu và chờ Gemini phân tích...'):
                        ai_result = get_ai_analysis(data_for_ai, api_key)
                        st.markdown("**Kết quả Phân tích từ Gemini AI:**")
                        st.info(ai_result)
                else:
                    st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets.")

    except ValueError as ve:
        st.error(f"Lỗi cấu trúc dữ liệu: {ve}")
    except Exception as e:
        st.error(f"Có lỗi xảy ra khi đọc hoặc xử lý file: {e}. Vui lòng kiểm tra định dạng file.")

else:
    st.info("Vui lòng tải lên file Excel để bắt đầu phân tích.")


# --- 6. Tích hợp Khung Chat Tương tác ---

st.divider()
st.subheader("6. Chat với Gemini 💬")
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
    st.error("Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets để sử dụng khung chat.")
else:
    # 1. Hiển thị lịch sử chat
    # Chú ý: Streamlit Chat Elements sử dụng role 'assistant', cần ánh xạ sang 'model' cho Gemini API
    for message in st.session_state["chat_messages"]:
        # Role 'model' của Session State được Streamlit hiển thị là 'assistant'
        display_role = 'assistant' if message['role'] == 'model' else message['role']
        with st.chat_message(display_role):
            st.markdown(message["content"])

    # 2. Xử lý đầu vào từ người dùng
    if prompt := st.chat_input("Hỏi tôi về các vấn đề tài chính, kinh tế hoặc yêu cầu tóm tắt thêm..."):
        
        # Thêm tin nhắn của người dùng vào lịch sử (role: user)
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})
        
        # Hiển thị tin nhắn người dùng
        with st.chat_message("user"):
            st.markdown(prompt)
            
        # Gọi API và lấy phản hồi (role: model)
        # Sử dụng st.session_state.chat_messages để duy trì ngữ cảnh
        with st.chat_message("assistant"): # Hiển thị phản hồi với role 'assistant'
            with st.spinner("Đang chờ Gemini trả lời..."):
                response_text = get_chat_response(st.session_state["chat_messages"], api_key)
                st.markdown(response_text)
                
            # Thêm phản hồi của model vào lịch sử (LƯU VỚI ROLE 'model' cho API call tiếp theo)
            st.session_state["chat_messages"].append({"role": "model", "content": response_text})
