package com.offblink.spore.fx;

import javafx.geometry.Insets;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TreeCell;
import javafx.scene.control.TreeItem;
import javafx.scene.control.TreeView;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 科目管理页：多级树（parent_id 呈现）+ 新建/改名/启停/删除。
 * 口径仿 Spore 远端：改名不动成员、删除只解绑文章（回未分组），语义由服务端保证。
 * 树节点值 = CatItem 数据对象（JavaFX 8 的 TreeItem 无属性表，值对象直存 id/status）。
 */
public class CategoriesPane extends VBox {

    private final ApiClient api;
    private final MainStage stage;
    private final TreeView<CatItem> tree = new TreeView<CatItem>();

    public CategoriesPane(ApiClient api, MainStage stage) {
        this.api = api;
        this.stage = stage;

        tree.setShowRoot(false);
        tree.setCellFactory(tv -> new TreeCell<CatItem>() {
            @Override
            protected void updateItem(CatItem item, boolean empty) {
                super.updateItem(item, empty);
                if (empty || item == null) {
                    setText(null);
                } else {
                    setText(item.name + (item.status == 0 ? "（停用）" : ""));
                }
            }
        });

        Button addRoot = new Button("新建顶层科目");
        addRoot.setOnAction(e -> create(null));
        Button addChild = new Button("新建子科目");
        addChild.setOnAction(e -> {
            CatItem sel = selectedNode();
            if (sel == null) {
                stage.showError(new IllegalArgumentException("先在树上选中一个父科目"));
                return;
            }
            create(sel.id);
        });
        Button rename = new Button("改名");
        rename.setOnAction(e -> rename());
        Button toggle = new Button("启/停");
        toggle.setOnAction(e -> toggleStatus());
        Button del = new Button("删除");
        del.setOnAction(e -> delete());
        Button refresh = new Button("刷新");
        refresh.setOnAction(e -> reload());

        Label hint = new Label("删除科目 = 墓碑 + 其下记录回「未分组」（记录一条不删）");
        hint.setStyle("-fx-text-fill: #888;");

        HBox toolbar = new HBox(8, addRoot, addChild, rename, toggle, del, refresh);
        toolbar.setPadding(new Insets(8));

        getChildren().addAll(toolbar, tree, hint);
        VBox.setVgrow(tree, Priority.ALWAYS);

        reload();
    }

    private void reload() {
        Fx.supply(() -> api.categoryTree().getJSONArray("data"), data -> {
            TreeItem<CatItem> root = new TreeItem<CatItem>();
            buildItems(data, root);
            tree.setRoot(root);
        }, stage::showError);
    }

    private void buildItems(JSONArray nodes, TreeItem<CatItem> parent) {
        for (int i = 0; i < nodes.length(); i++) {
            JSONObject n = nodes.getJSONObject(i);
            TreeItem<CatItem> item = new TreeItem<CatItem>(new CatItem(
                    n.getString("id"), n.getString("name"), n.optInt("status", 1)));
            parent.getChildren().add(item);
            buildItems(n.optJSONArray("children"), item);
        }
    }

    private CatItem selectedNode() {
        TreeItem<CatItem> item = tree.getSelectionModel().getSelectedItem();
        return (item == null) ? null : item.getValue();
    }

    private void create(String parentId) {
        javafx.scene.control.TextInputDialog dialog = new javafx.scene.control.TextInputDialog();
        dialog.setTitle("新建科目");
        dialog.setHeaderText(parentId == null ? "新建顶层科目" : "新建子科目");
        dialog.setContentText("名称：");
        dialog.showAndWait().ifPresent(name -> {
            if (name.trim().isEmpty()) {
                return;
            }
            Fx.async(() -> api.createCategory(name.trim(), parentId), this::reload, stage::showError);
        });
    }

    private void rename() {
        CatItem sel = selectedNode();
        if (sel == null) {
            return;
        }
        javafx.scene.control.TextInputDialog dialog =
                new javafx.scene.control.TextInputDialog(sel.name);
        dialog.setTitle("改名");
        dialog.setHeaderText("科目改名（成员归属不变）");
        dialog.setContentText("新名称：");
        dialog.showAndWait().ifPresent(name -> {
            if (name.trim().isEmpty() || name.trim().equals(sel.name)) {
                return;
            }
            Fx.async(() -> api.renameCategory(sel.id, name.trim()), this::reload, stage::showError);
        });
    }

    private void toggleStatus() {
        CatItem sel = selectedNode();
        if (sel == null) {
            return;
        }
        int next = sel.status == 1 ? 0 : 1;
        Fx.async(() -> api.changeCategoryStatus(sel.id, next), this::reload, stage::showError);
    }

    private void delete() {
        CatItem sel = selectedNode();
        if (sel == null) {
            return;
        }
        javafx.scene.control.Alert confirm = new javafx.scene.control.Alert(
                javafx.scene.control.Alert.AlertType.CONFIRMATION);
        confirm.setHeaderText("删除科目「" + sel.name + "」？");
        confirm.setContentText("科目留墓碑随同步传播；其下记录回「未分组」，记录本身不删。");
        confirm.showAndWait().ifPresent(bt -> {
            if (bt == javafx.scene.control.ButtonType.OK) {
                Fx.async(() -> api.deleteCategory(sel.id), this::reload, stage::showError);
            }
        });
    }

    /** 树节点数据（JavaFX 8 TreeItem 无属性表，走值对象） */
    private static class CatItem {
        final String id;
        final String name;
        final int status;

        CatItem(String id, String name, int status) {
            this.id = id;
            this.name = name;
            this.status = status;
        }
    }
}
