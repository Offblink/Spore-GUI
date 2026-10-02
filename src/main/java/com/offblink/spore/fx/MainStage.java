package com.offblink.spore.fx;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Scene;
import javafx.scene.control.Alert;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.Tab;
import javafx.scene.control.TabPane;
import javafx.scene.control.TextField;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import javafx.stage.Stage;

/**
 * JavaFX 主窗口：登录 → 三页签（搜题记录 / 科目管理 / 设置）。
 * UI 只经 ApiClient 走 REST——不注入 service 不直连 DB（handoff §1 单进程纪律）。
 */
public class MainStage extends Stage {

    private final ApiClient api = new ApiClient();

    public MainStage() {
        setTitle("Spore 搜题内容管理系统");
        setScene(buildBootingScene());
        silentLogin();
    }

    /** 启动占位场景（静默登录探测中，通常一闪而过） */
    private Scene buildBootingScene() {
        Label boot = new Label("正在检查本机登录状态…");
        boot.setStyle("-fx-text-fill: #666;");
        VBox root = new VBox(boot);
        root.setPadding(new Insets(40));
        root.setAlignment(Pos.CENTER);
        return new Scene(root, 420, 300);
    }

    /**
     * B 方案静默登录：本机 device.token 存在且有效 → 直进主界面；
     * 无文件/失效（40101、服务端轮换过）→ 清残留回登录页。
     * 换到的仍是普通 JWT——REST 权限模型零改动。
     */
    private void silentLogin() {
        String saved = DeviceTokenStore.read();
        if (saved == null) {
            setScene(buildLoginScene());
            return;
        }
        Fx.async(() -> {
            if (!api.deviceLogin(saved)) {
                DeviceTokenStore.clear();
                throw new IllegalStateException("TOKEN_INVALID");
            }
        }, () -> setScene(buildMainScene()),
                e -> setScene(buildLoginScene()));
    }

    private Scene buildLoginScene() {
        Label title = new Label("Spore-GUI 登录");
        title.setStyle("-fx-font-size: 20px; -fx-font-weight: bold;");

        TextField username = new TextField();
        username.setPromptText("用户名");
        PasswordField password = new PasswordField();
        password.setPromptText("密码");
        password.setSkin(new AsteriskSkin(password));
        // 明文镜像字段：PasswordField 掩码关不掉(JavaFX 8 无 setEchoChar)，
        // 可见性切换 = 在掩码/明文两个字段间换，文本双向同步
        TextField plain = new TextField();
        plain.setPromptText("密码");
        plain.setVisible(false);
        plain.setManaged(false);
        final boolean[] revealed = {false};
        Label status = new Label();
        status.setStyle("-fx-text-fill: #d33;");

        Button loginBtn = new Button("登录");
        Button registerBtn = new Button("注册首个管理员");
        // 状态即按钮：🙈=当前隐藏，点击变 👀=当前可见
        Button eyeBtn = new Button("🙈");
        loginBtn.setDefaultButton(true);

        Runnable doLogin = () -> {
            status.setText("");
            String u = username.getText();
            String p = revealed[0] ? plain.getText() : password.getText();
            Fx.async(() -> {
                api.login(u, p);
                // 登录成功 → 轮换并存本机令牌（下次启动免输口令）
                DeviceTokenStore.write(api.createDeviceToken());
            }, () -> setScene(buildMainScene()),
                e -> status.setText(e.getMessage()));
        };
        loginBtn.setOnAction(e -> doLogin.run());
        password.setOnAction(e -> doLogin.run());
        plain.setOnAction(e -> doLogin.run());
        registerBtn.setOnAction(e -> {
            status.setText("");
            String u = username.getText();
            String p = revealed[0] ? plain.getText() : password.getText();
            Fx.async(() -> api.register(u, p),
                    doLogin::run,
                    ex -> status.setText(ex.getMessage()));
        });
        eyeBtn.setOnAction(e -> {
            boolean show = !revealed[0];
            if (show) {
                plain.setText(password.getText());
                password.setVisible(false);
                password.setManaged(false);
                plain.setVisible(true);
                plain.setManaged(true);
                plain.requestFocus();
                plain.positionCaret(plain.getLength());
                eyeBtn.setText("👀");
            } else {
                password.setText(plain.getText());
                plain.setVisible(false);
                plain.setManaged(false);
                password.setVisible(true);
                password.setManaged(true);
                password.requestFocus();
                password.positionCaret(password.getLength());
                eyeBtn.setText("🙈");
            }
            revealed[0] = show;
        });

        GridPane form = new GridPane();
        form.setHgap(10);
        form.setVgap(10);
        form.add(new Label("用户名"), 0, 0);
        form.add(username, 1, 0);
        form.add(new Label("密码"), 0, 1);
        form.add(password, 1, 1);
        form.add(plain, 1, 1); // 与 password 同格互斥显示(managed/visible 切换)
        form.add(eyeBtn, 2, 1);

        HBox buttons = new HBox(10, loginBtn, registerBtn);
        buttons.setAlignment(Pos.CENTER);

        VBox root = new VBox(16, title, form, buttons, status);
        root.setPadding(new Insets(30));
        root.setAlignment(Pos.CENTER);
        return new Scene(root, 420, 300);
    }

    private Scene buildMainScene() {
        RecordsPane records = new RecordsPane(api, this);
        CategoriesPane categories = new CategoriesPane(api, this);
        SettingsPane settings = new SettingsPane(api, this);

        TabPane tabs = new TabPane();
        Tab tabRecords = new Tab("搜题记录", records);
        Tab tabCats = new Tab("科目管理", categories);
        Tab tabSettings = new Tab("设置", settings);
        tabRecords.setClosable(false);
        tabCats.setClosable(false);
        tabSettings.setClosable(false);
        tabs.getTabs().addAll(tabRecords, tabCats, tabSettings);

        HBox statusBar = new HBox(10);
        statusBar.setPadding(new Insets(6, 10, 6, 10));
        Label user = new Label("加载中…");
        Fx.supply(() -> api.me().getJSONObject("data"),
                me -> user.setText(me.getString("username") + "（" + me.optString("roleName") + "）"),
                e -> user.setText("?"));
        Button logout = new Button("退出登录");
        logout.setOnAction(e -> {
            api.logout();
            DeviceTokenStore.clear();
            setScene(buildLoginScene());
        });
        statusBar.getChildren().addAll(user, logout);

        VBox root = new VBox(tabs, statusBar);
        VBox.setVgrow(tabs, javafx.scene.layout.Priority.ALWAYS);
        Scene scene = new Scene(root, 1000, 680);
        setScene(scene);
        return scene;
    }

    /** 统一错误弹窗（各页签共用） */
    void showError(Throwable t) {
        Alert alert = new Alert(Alert.AlertType.ERROR);
        alert.setHeaderText(null);
        alert.setContentText(t.getMessage() == null ? t.toString() : t.getMessage());
        alert.showAndWait();
    }
}
