/*
 * Ruizu scan encoder — libjpeg-turbo YUV420 compress + 623-byte AVI1 header graft.
 */
#include "ruizu_scan.h"
#include "ruizu_tables.h"
#include "ruizu_header.h"

#include <stdlib.h>
#include <string.h>
#include <turbojpeg.h>

#define RUIZU_SCAN_TMP_CAP (256 * 1024)

struct RuizuScanEnc {
    int width;
    int height;
    int vendor_quality;
    int ijg_quality;
    tjhandle tj;
    uint8_t *tmp;
    unsigned long tmp_cap;
};

int ruizu_scan_vendor_to_ijg_quality(int vendor_quality)
{
    /*
     * libjpeg-turbo uses IJG default quant tables in the scan body; the 623-byte
     * graft supplies Ruizu DQT/DHT. Tier 14 ≈ turbo q75 → scan ~10900 B (official
     * ~10945). Ruizu-quant encoding (cjpeg -qtables) uses q≈50 — see
     * ruizu_scan_enc.encode_cjpeg().
     */
    if (vendor_quality < RUIZU_SCAN_QUALITY_MIN)
        vendor_quality = RUIZU_SCAN_QUALITY_MIN;
    if (vendor_quality > RUIZU_SCAN_QUALITY_MAX)
        vendor_quality = RUIZU_SCAN_QUALITY_MAX;
    return 75 + (vendor_quality - RUIZU_SCAN_QUALITY_MIN) * 2;
}

static int find_entropy_offset(const uint8_t *data, size_t len)
{
    size_t i = 2;

    while (i + 3 < len) {
        if (data[i] != 0xff)
            return -1;
        if (data[i + 1] == 0xda) {
            uint16_t seg_len = (uint16_t)((data[i + 2] << 8) | data[i + 3]);
            return (int)(i + 2 + seg_len);
        }
        if (data[i + 1] == 0x00)
            i++;
        else {
            uint16_t seg_len = (uint16_t)((data[i + 2] << 8) | data[i + 3]);
            i += 2 + seg_len;
        }
    }
    return -1;
}

RuizuScanEnc *ruizu_scan_enc_open(int width, int height, int quality)
{
    RuizuScanEnc *enc = calloc(1, sizeof(*enc));

    if (!enc)
        return NULL;
    enc->width = width;
    enc->height = height;
    enc->vendor_quality = quality;
    enc->ijg_quality = ruizu_scan_vendor_to_ijg_quality(quality);
    enc->tj = tjInitCompress();
    enc->tmp = malloc(RUIZU_SCAN_TMP_CAP);
    enc->tmp_cap = RUIZU_SCAN_TMP_CAP;
    if (!enc->tj || !enc->tmp) {
        ruizu_scan_enc_close(enc);
        return NULL;
    }
    return enc;
}

void ruizu_scan_enc_close(RuizuScanEnc *enc)
{
    if (!enc)
        return;
    if (enc->tj)
        tjDestroy(enc->tj);
    free(enc->tmp);
    free(enc);
}

int ruizu_scan_enc_frame(RuizuScanEnc *enc, const uint8_t *yuv420,
                         uint8_t *out, size_t out_cap)
{
    const unsigned char *planes[3];
    int strides[3];
    unsigned char *jpeg_buf = enc->tmp;
    unsigned long jpeg_size = enc->tmp_cap;
    const uint8_t *y_plane;
    const uint8_t *cb_plane;
    const uint8_t *cr_plane;
    int body_off, total;
    int rc;

    if (!enc || !yuv420 || !out || !enc->tj || !enc->tmp)
        return -1;
    if (out_cap < 8192)
        return -2;

    y_plane = yuv420;
    cb_plane = yuv420 + (size_t)enc->width * enc->height;
    cr_plane = cb_plane + (size_t)(enc->width / 2) * (enc->height / 2);

    planes[0] = y_plane;
    planes[1] = cb_plane;
    planes[2] = cr_plane;
    strides[0] = enc->width;
    strides[1] = enc->width / 2;
    strides[2] = enc->width / 2;

    rc = tjCompressFromYUVPlanes(
        enc->tj, planes, enc->width, strides, enc->height, TJSAMP_420,
        &jpeg_buf, &jpeg_size, enc->ijg_quality, TJFLAG_ACCURATEDCT);
    if (rc != 0)
        return -3;

    if (jpeg_size < 4 || enc->tmp[0] != 0xff || enc->tmp[1] != 0xd8)
        return -4;

    body_off = find_entropy_offset(enc->tmp, jpeg_size);
    if (body_off < 0)
        return -5;

    total = RUIZU_JPEG_HEADER_SIZE + (int)jpeg_size - body_off;
    if ((size_t)total > out_cap)
        return -6;

    memcpy(out, ruizu_jpeg_header, RUIZU_JPEG_HEADER_SIZE);
    memcpy(out + RUIZU_JPEG_HEADER_SIZE, enc->tmp + body_off, jpeg_size - (size_t)body_off);
    return total;
}
