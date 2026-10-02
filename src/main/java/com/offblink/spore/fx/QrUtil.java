package com.offblink.spore.fx;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.EncodeHintType;
import com.google.zxing.WriterException;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel;
import javafx.embed.swing.SwingFXUtils;
import javafx.scene.image.ImageView;
import javafx.scene.image.WritableImage;

import java.awt.Color;
import java.awt.image.BufferedImage;
import java.util.EnumMap;
import java.util.Map;

/**
 * 二维码渲染（设置页扫码配对）：zxing 生成 → BufferedImage → JavaFX Image。
 */
public final class QrUtil {

    private QrUtil() {
    }

    public static ImageView render(String content, int size) {
        try {
            Map<EncodeHintType, Object> hints = new EnumMap<EncodeHintType, Object>(EncodeHintType.class);
            hints.put(EncodeHintType.ERROR_CORRECTION, ErrorCorrectionLevel.M);
            hints.put(EncodeHintType.CHARACTER_SET, "UTF-8");
            hints.put(EncodeHintType.MARGIN, 1);
            BitMatrix matrix = new QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints);
            BufferedImage awt = new BufferedImage(size, size, BufferedImage.TYPE_INT_RGB);
            for (int x = 0; x < size; x++) {
                for (int y = 0; y < size; y++) {
                    awt.setRGB(x, y, matrix.get(x, y) ? Color.BLACK.getRGB() : Color.WHITE.getRGB());
                }
            }
            WritableImage fx = SwingFXUtils.toFXImage(awt, null);
            ImageView view = new ImageView(fx);
            view.setFitWidth(size);
            view.setFitHeight(size);
            view.setPreserveRatio(true);
            return view;
        } catch (WriterException e) {
            ImageView empty = new ImageView();
            empty.setFitWidth(size);
            empty.setFitHeight(size);
            return empty;
        }
    }
}
