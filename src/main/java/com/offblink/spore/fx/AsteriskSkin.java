package com.offblink.spore.fx;

import com.sun.javafx.scene.control.skin.TextFieldSkin;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;

import java.util.Arrays;

/**
 * 密码框掩码皮肤：JavaFX 8 的 TextFieldSkin.maskText 把掩码字符硬编码成
 * U+25CF(●)（且无 setEchoChar API），本机字体对该码位缺字形时显示成 □。
 * 覆写为 ASCII '*'——任何字体都实装，用户口径「实心圆形或星号」取星号。
 * 注入方式：password.setSkin(new AsteriskSkin(password))（modena 未用 -fx-skin 覆盖 text-field，
 * 程序化 setSkin 在 CSS 阶段因 skin 非空不会被 createDefaultSkin 顶掉）。
 */
public class AsteriskSkin extends TextFieldSkin {

    public AsteriskSkin(TextField control) {
        super(control);
    }

    @Override
    protected String maskText(String txt) {
        if (txt == null || txt.isEmpty()) {
            return txt;
        }
        if (getSkinnable() instanceof PasswordField) {
            char[] mask = new char[txt.length()];
            Arrays.fill(mask, '*');
            return new String(mask);
        }
        return txt;
    }
}
