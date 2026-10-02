package com.offblink.spore.fx;

import javafx.geometry.Insets;
import javafx.scene.control.Alert;
import javafx.scene.control.Button;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Label;
import javafx.scene.control.Separator;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import javafx.stage.DirectoryChooser;
import org.json.JSONObject;

import java.io.File;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;

/**
 * 设置页：① 题库目录（选择 + 迁移协议确认，handoff §2）；② 扫码配对（LAN token 二维码 + 文本兜底）。
 * 二维码 IP 枚举：site-local IPv4，跳过 loopback/169.254/虚拟网卡（design/02 认证节）。
 */
public class SettingsPane extends VBox {

    private final ApiClient api;
    private final MainStage stage;

    private final Label storagePath = new Label("加载中…");
    private final Label storageStat = new Label();
    private final Label lanToken = new Label();
    private final VBox qrBox = new VBox();
    private final Label ipLabel = new Label();

    public SettingsPane(ApiClient api, MainStage stage) {
        this.api = api;
        this.stage = stage;

        // ---- 题库目录 ----
        Label h1 = new Label("题库目录");
        h1.setStyle("-fx-font-size: 16px; -fx-font-weight: bold;");
        storagePath.setWrapText(true);
        Button choose = new Button("选择目录并迁移…");
        choose.setOnAction(e -> chooseStorage());
        Button refreshStorage = new Button("刷新");
        refreshStorage.setOnAction(e -> reloadStorage());
        HBox storageBar = new HBox(8, choose, refreshStorage);

        // ---- 扫码配对 ----
        Label h2 = new Label("扫码配对（手机同步）");
        h2.setStyle("-fx-font-size: 16px; -fx-font-weight: bold;");
        lanToken.setStyle("-fx-font-family: 'Consolas', monospace; -fx-font-size: 13px;");
        Button refreshQr = new Button("刷新二维码");
        refreshQr.setOnAction(e -> reloadQr());
        ipLabel.setStyle("-fx-text-fill: #666;");

        VBox qrPane = new VBox(8, qrBox, ipLabel, lanToken, refreshQr);

        GridPane grid = new GridPane();
        grid.setHgap(12);
        grid.setVgap(8);
        grid.add(h1, 0, 0);
        grid.add(storagePath, 0, 1);
        grid.add(storageStat, 0, 2);
        grid.add(storageBar, 0, 3);
        grid.add(new Separator(), 0, 4);
        grid.add(h2, 0, 5);
        grid.add(qrPane, 0, 6);

        VBox root = new VBox(grid);
        root.setPadding(new Insets(16));
        getChildren().add(root);

        reloadStorage();
        reloadQr();
    }

    private void reloadStorage() {
        Fx.supply(() -> api.storageInfo().getJSONObject("data"), info -> {
            storagePath.setText(info.getString("path"));
            storageStat.setText("文件数 " + info.getLong("fileCount")
                    + "　总大小 " + humanBytes(info.getLong("bytes")));
        }, stage::showError);
    }

    /** 迁移协议确认（handoff §2）：copy → 校验 → 切配置 → 删旧，失败留在旧目录 */
    private void chooseStorage() {
        DirectoryChooser chooser = new DirectoryChooser();
        chooser.setTitle("选择新的题库目录（将执行迁移协议）");
        File dir = chooser.showDialog(stage);
        if (dir == null) {
            return;
        }
        Alert confirm = new Alert(Alert.AlertType.CONFIRMATION);
        confirm.setTitle("切换题库目录");
        confirm.setHeaderText("迁移到：\n" + dir.getAbsolutePath());
        confirm.setContentText("协议：copy → 校验（文件数+字节数）→ 切配置 → 删旧目录。\n"
                + "任一步失败留在原目录，配置不动。DB 只存相对路径，数据行零改动。");
        confirm.showAndWait().ifPresent(bt -> {
            if (bt != ButtonType.OK) {
                return;
            }
            Fx.async(() -> api.switchStorage(dir.getAbsolutePath()), () -> {
                reloadStorage();
                Alert done = new Alert(Alert.AlertType.INFORMATION);
                done.setHeaderText(null);
                done.setContentText("迁移完成");
                done.showAndWait();
            }, stage::showError);
        });
    }

    private void reloadQr() {
        Fx.async(() -> {
            // 后台线程：取 token + 选 IP，结果经字段带回（lambda 不可改外部数组）
            qrToken = api.lanToken();
            qrIp = pickLanIp();
        }, () -> {
            try {
                String token = qrToken;
                String ip = qrIp;
                lanToken.setText("LAN token（手输兜底）： " + token);
                if (ip == null) {
                    qrBox.getChildren().clear();
                    ipLabel.setText("未找到可用局域网地址——请确认已连 Wi-Fi/热点");
                    return;
                }
                String payload = "{\"v\":1,\"api\":\"http://" + ip + ":8080/api\",\"token\":\"" + token + "\"}";
                qrBox.getChildren().setAll(QrUtil.render(payload, 220));
                ipLabel.setText("PC 局域网地址：" + ip + ":8080（换网后点刷新）");
            } catch (Exception e) {
                stage.showError(e);
            }
        }, stage::showError);
    }

    // Fx.async 的任务在后台线程跑，结果经字段带回 UI 线程
    private volatile String qrToken;
    private volatile String qrIp;

    /** 选一块可用的局域网网卡地址：site-local IPv4，跳过虚拟网卡 */
    private String pickLanIp() {
        try {
            List<String> fallback = new ArrayList<>();
            Enumeration<NetworkInterface> nifs = NetworkInterface.getNetworkInterfaces();
            while (nifs.hasMoreElements()) {
                NetworkInterface nif = nifs.nextElement();
                if (!nif.isUp() || nif.isLoopback() || nif.isVirtual()) {
                    continue;
                }
                String name = nif.getName().toLowerCase();
                if (name.startsWith("vethernet") || name.startsWith("wsl")
                        || name.contains("vmware") || name.contains("virtualbox")
                        || name.contains("hyperv")) {
                    continue;
                }
                Enumeration<InetAddress> addrs = nif.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (!(a instanceof Inet4Address) || a.isLoopbackAddress()) {
                        continue;
                    }
                    if (!a.isSiteLocalAddress()) {
                        continue; // 跳过 169.254 APIPA 与公网地址
                    }
                    // 优先物理感强的名字（Wi-Fi/以太网），热点适配器留作次选
                    if (name.contains("wi-fi") || name.contains("wlan") || name.contains("ethernet")) {
                        return a.getHostAddress();
                    }
                    fallback.add(a.getHostAddress());
                }
            }
            return fallback.isEmpty() ? null : fallback.get(0);
        } catch (Exception e) {
            return null;
        }
    }

    private static String humanBytes(long bytes) {
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024 * 1024) {
            return String.format("%.1f KB", bytes / 1024.0);
        }
        if (bytes < 1024L * 1024 * 1024) {
            return String.format("%.1f MB", bytes / (1024.0 * 1024));
        }
        return String.format("%.2f GB", bytes / (1024.0 * 1024 * 1024));
    }
}
