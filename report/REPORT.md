# Báo cáo Day 6: [ĐIỀN tên đề tài ngắn]

> Thay **mọi** ô có chữ ĐIỀN nằm trong ngoặc vuông bằng nội dung của bạn, xoá luôn cả dấu ngoặc vuông. Lệnh `python tools/check_submission.py` sẽ báo FAIL nếu còn sót bất kỳ chỗ nào.

- **Họ tên:** Bùi Việt Anh
- **MSSV:** 2A202602611
- **Lớp:** 3b-track4
- **Link repo:** https://github.com/VietAnh-AI2-UET/BuiVietAnh-2A202602611-Track4-Day21.git
- **Topic:** F
- **Dataset:** data/kitti_mini (thí nghiệm chính), data/synthetic (kiểm tra code)
- **Các frame đã dùng:** 000008, 000010, 000011, 000004, 000016, 000049

## 1. Claim

Một câu khẳng định kỹ thuật có thể kiểm chứng:

- ***Trên ít nhất 10 đối tượng Car không bị che khuất và nằm trọn trong ảnh của data/kitti_mini, ít nhất 70% hộp 2D tạo bằng cách chiếu 8 góc hộp 3D lên ảnh có IoU ≥ 0,7 so với hộp 2D trong nhãn gốc.***

## 2. Evidence

Bảng hoặc plot số liệu, kèm ảnh/video demo. Ghi rõ đường dẫn file trong `results/`.

| Cấu hình / mức perturb | Metric 1 | Metric 2 | Ghi chú |
|---|---|---|---|
| [ĐIỀN] | | | |

![demo](../results/figures/[ĐIỀN].png)

## 3. Failure case

Nêu khi nào hệ thống hoặc phương pháp fail, vì sao fail, và liên hệ tới lớp nào trong 6 lớp debug: I/O, Geometry, Time, Preprocess, Model, Metric.

![failure](../results/figures/fail_[ĐIỀN].png)

[ĐIỀN]

## 4. Khuyến nghị nếu triển khai thật

Use-case cụ thể (ADAS / robot / drone), trade-off và bước tiếp theo.

[ĐIỀN]

## 5. Cách chạy lại

Các lệnh tái tạo lại toàn bộ kết quả từ repo sạch.

```bash
[ĐIỀN]
```

## 6. Khai báo sử dụng AI

Ghi rõ đã dùng công cụ AI nào, dùng vào việc gì, và bạn đã tự kiểm chứng kết quả đó bằng cách nào. Nếu không dùng AI, ghi "Không sử dụng". Xem quy định ở `RULES.md` mục 2.

| Công cụ | Dùng cho việc gì | Bạn đã kiểm chứng thế nào |
|---|---|---|
| [ĐIỀN] | | |
