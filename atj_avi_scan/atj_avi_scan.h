/*
 * ATJ AVI MJPEG scan encoder — native reimplementation (libjpeg-turbo / IJG API).
 *
 * Produces AVI1-style JPEG frames matching vendor AVI_EncDLL scan sizes (~11 KB
 * for 128x128) by encoding with ATJ AVI quant tables and remapping the prefix.
 */
#ifndef ATJ_AVI_SCAN_H
#define ATJ_AVI_SCAN_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ATJ_AVI_SCAN_QUALITY_MIN 14
#define ATJ_AVI_SCAN_QUALITY_MAX 22
#define ATJ_AVI_SCAN_QUALITY_DEFAULT 22

typedef struct AtjAviScanEnc AtjAviScanEnc;

/* quality: vendor tier from AmvTransform.ini AVISIZE=128X128(14;22;22) */
AtjAviScanEnc *atj_avi_scan_enc_open(int width, int height, int quality);
void          atj_avi_scan_enc_close(AtjAviScanEnc *enc);

/*
 * Encode one YUV420P frame (width*height*3/2 bytes, planar Y,U,V).
 * Returns total JPEG size on success, or a negative error code.
 */
int atj_avi_scan_enc_frame(AtjAviScanEnc *enc,
                         const uint8_t *yuv420,
                         uint8_t *out,
                         size_t out_cap);

/* Map vendor quality (14..22) to libjpeg quality (1..100). */
int atj_avi_scan_vendor_to_ijg_quality(int vendor_quality);

#ifdef __cplusplus
}
#endif

#endif /* ATJ_AVI_SCAN_H */
