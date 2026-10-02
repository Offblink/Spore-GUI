package com.offblink.spore.fx;

import javafx.application.Platform;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * JavaFX 线程小工具：后台跑网络/磁盘，回 UI 线程刷新——绝不阻塞 FX Application Thread。
 */
public final class Fx {

    /** 后台任务：允许受检异常（ApiClient 全部方法都 throws Exception） */
    @FunctionalInterface
    public interface Task {
        void run() throws Exception;
    }

    private static final ExecutorService POOL = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "fx-bg");
        t.setDaemon(true);
        return t;
    });

    private Fx() {
    }

    /** 后台执行 task，成功回 FX 线程执行 onUi；异常走默认错误弹窗 */
    public static void async(Task task, Runnable onUi) {
        async(task, onUi, Fx::showError);
    }

    public static void async(Task task, Runnable onUi, java.util.function.Consumer<Throwable> onError) {
        POOL.execute(() -> {
            try {
                task.run();
                Platform.runLater(onUi);
            } catch (Throwable t) {
                Platform.runLater(() -> onError.accept(t));
            }
        });
    }

    /** 后台执行 supplier 拿结果，回 FX 线程消费——REST 调用必须走这个（FX 线程禁网） */
    public static <T> void supply(java.util.concurrent.Callable<T> supplier,
                                  java.util.function.Consumer<T> onUi,
                                  java.util.function.Consumer<Throwable> onError) {
        POOL.execute(() -> {
            try {
                T result = supplier.call();
                Platform.runLater(() -> onUi.accept(result));
            } catch (Throwable t) {
                Platform.runLater(() -> onError.accept(t));
            }
        });
    }

    private static void showError(Throwable t) {
        javafx.scene.control.Alert alert = new javafx.scene.control.Alert(
                javafx.scene.control.Alert.AlertType.ERROR);
        alert.setHeaderText(null);
        alert.setContentText(t.getMessage() == null ? t.toString() : t.getMessage());
        alert.showAndWait();
    }
}
