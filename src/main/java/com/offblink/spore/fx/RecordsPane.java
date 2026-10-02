package com.offblink.spore.fx;

import javafx.collections.FXCollections;
import javafx.collections.ObservableList;
import javafx.geometry.Insets;
import javafx.scene.control.Button;
import javafx.scene.control.ComboBox;
import javafx.scene.control.ContextMenu;
import javafx.scene.control.Label;
import javafx.scene.control.MenuItem;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.control.TableRow;
import javafx.scene.control.TextField;
import javafx.scene.control.TextInputDialog;
import javafx.scene.control.cell.PropertyValueFactory;
import javafx.scene.input.MouseButton;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import org.json.JSONArray;
import org.json.JSONObject;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 搜题记录页三件套（handoff §2，交互仿 Spore 远端 0ed3da2）：
 * ① 顶部「新建科目」命名框（置顶目录形态）；② 会话行右键「移入科目」；③ 按科目筛选。
 */
public class RecordsPane extends VBox {

    private final ApiClient api;
    private final MainStage stage;

    private final TextField search = new TextField();
    private final ComboBox<CatOption> catFilter = new ComboBox<>();
    private final TableView<RecordRow> table = new TableView<>();
    private final ObservableList<RecordRow> rows = FXCollections.observableArrayList();
    private final ObservableList<CatOption> catOptions = FXCollections.observableArrayList();

    public RecordsPane(ApiClient api, MainStage stage) {
        this.api = api;
        this.stage = stage;

        search.setPromptText("按标题搜索…");
        search.setPrefWidth(220);
        search.setOnAction(e -> refresh());

        catFilter.setItems(catOptions);
        catFilter.setPrefWidth(180);
        catFilter.setOnAction(e -> refresh());

        Button searchBtn = new Button("查询");
        searchBtn.setOnAction(e -> refresh());
        Button newCatBtn = new Button("新建科目");
        newCatBtn.setOnAction(e -> createSubject());
        Button refreshBtn = new Button("刷新");
        refreshBtn.setOnAction(e -> reloadCats());

        HBox toolbar = new HBox(8, search, searchBtn, catFilter, newCatBtn, refreshBtn);
        toolbar.setPadding(new Insets(8));

        setupTable();

        getChildren().addAll(toolbar, table);
        VBox.setVgrow(table, Priority.ALWAYS);

        reloadCats();
        refresh();
    }

    private void setupTable() {
        TableColumn<RecordRow, String> colTitle = new TableColumn<>("标题");
        colTitle.setCellValueFactory(new PropertyValueFactory<>("title"));
        colTitle.setPrefWidth(320);

        TableColumn<RecordRow, String> colCat = new TableColumn<>("科目");
        colCat.setCellValueFactory(new PropertyValueFactory<>("categoryName"));
        colCat.setPrefWidth(140);

        TableColumn<RecordRow, String> colStatus = new TableColumn<>("状态");
        colStatus.setCellValueFactory(new PropertyValueFactory<>("status"));
        colStatus.setPrefWidth(90);

        TableColumn<RecordRow, String> colOrigin = new TableColumn<>("来源");
        colOrigin.setCellValueFactory(new PropertyValueFactory<>("origin"));
        colOrigin.setPrefWidth(70);

        TableColumn<RecordRow, String> colTime = new TableColumn<>("更新时间");
        colTime.setCellValueFactory(new PropertyValueFactory<>("updateTime"));
        colTime.setPrefWidth(170);

        table.getColumns().addAll(colTitle, colCat, colStatus, colOrigin, colTime);
        table.setItems(rows);
        table.setRowFactory(tv -> {
            TableRow<RecordRow> row = new TableRow<RecordRow>();
            MenuItem move = new MenuItem("移入科目…");
            move.setOnAction(e -> moveToSubject(row.getItem()));
            MenuItem del = new MenuItem("删除");
            del.setOnAction(e -> deleteRecord(row.getItem()));
            row.setContextMenu(new ContextMenu(move, del));
            row.setOnMouseClicked(ev -> {
                if (ev.getButton() == MouseButton.SECONDARY && !row.isEmpty()) {
                    row.getContextMenu().show(row, ev.getScreenX(), ev.getScreenY());
                }
            });
            return row;
        });
    }

    /** 重新拉科目树 → 筛选下拉（顶层在前，子级缩进呈现） */
    private void reloadCats() {
        Fx.supply(() -> api.categoryTree().getJSONArray("data"), tree -> {
            catOptions.clear();
            catOptions.add(new CatOption(null, "（全部科目）"));
            flatten(tree, 0, catOptions);
        }, stage::showError);
    }

    private void flatten(JSONArray nodes, int depth, ObservableList<CatOption> out) {
        for (int i = 0; i < nodes.length(); i++) {
            JSONObject n = nodes.getJSONObject(i);
            out.add(new CatOption(n.getString("id"),
                    indent(depth) + n.getString("name")
                            + (n.optInt("status", 1) == 0 ? "（停用）" : "")));
            flatten(n.optJSONArray("children"), depth + 1, out);
        }
    }

    private static String indent(int depth) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < depth; i++) {
            sb.append('　');
        }
        return sb.toString();
    }

    private void refresh() {
        CatOption sel = catFilter.getValue();
        String catId = (sel == null) ? null : sel.id;
        String kw = search.getText();
        Fx.supply(() -> api.articles(kw, catId).getJSONObject("data").getJSONArray("list"),
                list -> {
                    rows.clear();
                    for (int i = 0; i < list.length(); i++) {
                        JSONObject a = list.getJSONObject(i);
                        rows.add(new RecordRow(
                                a.getString("id"),
                                a.getString("title"),
                                a.optString("categoryName", a.isNull("categoryId") ? "" : "已删科目"),
                                a.optString("status", ""),
                                a.optString("origin", ""),
                                a.optString("updateTime", "").replace('T', ' ')));
                    }
                }, stage::showError);
    }

    /** ① 新建科目：命名即建、置顶呈现（Spore 口径：trim、≤40 字） */
    private void createSubject() {
        TextInputDialog dialog = new TextInputDialog();
        dialog.setTitle("新建科目");
        dialog.setHeaderText("科目名（目录形态置顶，可拖入会话）");
        dialog.setContentText("名称：");
        Optional<String> result = dialog.showAndWait();
        if (!result.isPresent() || result.get().trim().isEmpty()) {
            return;
        }
        String name = result.get().trim();
        Fx.async(() -> api.createCategory(name, null), () -> {
            reloadCats();
            refresh();
        }, stage::showError);
    }

    /** ② 移入科目：选会话行 → 挑科目（null = 移出回未分组） */
    private void moveToSubject(RecordRow item) {
        if (item == null) {
            return;
        }
        List<String> names = new ArrayList<>();
        List<String> ids = new ArrayList<>();
        for (CatOption o : catOptions) {
            if (o.id == null) {
                continue; // 跳过「全部」占位
            }
            names.add(o.label.replace('　', ' ').trim());
            ids.add(o.id);
        }
        javafx.scene.control.ChoiceDialog<String> dialog =
                new javafx.scene.control.ChoiceDialog<>(names.isEmpty() ? null : names.get(0), names);
        dialog.setTitle("移入科目");
        dialog.setHeaderText("把《" + item.title + "》移入：");
        dialog.setContentText("科目");
        dialog.getDialogPane().getButtonTypes().add(0,
                new javafx.scene.control.ButtonType("移出科目（回未分组）"));
        dialog.setResultConverter(bt -> {
            if (bt != null && bt.getText().startsWith("移出")) {
                return "";
            }
            return dialog.getResult();
        });
        Optional<String> r = dialog.showAndWait();
        if (!r.isPresent()) {
            return;
        }
        String catId = r.get().isEmpty() ? "" : ids.get(names.indexOf(r.get()));
        Fx.async(() -> api.moveArticle(item.id, catId), this::refresh, stage::showError);
    }

    private void deleteRecord(RecordRow item) {
        if (item == null) {
            return;
        }
        javafx.scene.control.Alert confirm = new javafx.scene.control.Alert(
                javafx.scene.control.Alert.AlertType.CONFIRMATION);
        confirm.setHeaderText("删除《" + item.title + "》？");
        confirm.setContentText("逻辑删除（墓碑），会随同步传播到手机。");
        confirm.showAndWait().ifPresent(bt -> {
            if (bt == javafx.scene.control.ButtonType.OK) {
                Fx.async(() -> api.deleteArticle(item.id), this::refresh, stage::showError);
            }
        });
    }

    /** 筛选下拉项：id=null 表示「全部」 */
    public static class CatOption {
        final String id;
        final String label;

        CatOption(String id, String label) {
            this.id = id;
            this.label = label;
        }

        @Override
        public String toString() {
            return label;
        }
    }

    /** 表格行（PropertyValueFactory 经 getter 取值） */
    public static class RecordRow {
        private final String id;
        private final String title;
        private final String categoryName;
        private final String status;
        private final String origin;
        private final String updateTime;

        public RecordRow(String id, String title, String categoryName,
                         String status, String origin, String updateTime) {
            this.id = id;
            this.title = title;
            this.categoryName = categoryName;
            this.status = status;
            this.origin = origin;
            this.updateTime = updateTime;
        }

        public String getId() {
            return id;
        }

        public String getTitle() {
            return title;
        }

        public String getCategoryName() {
            return categoryName;
        }

        public String getStatus() {
            return status;
        }

        public String getOrigin() {
            return origin;
        }

        public String getUpdateTime() {
            return updateTime;
        }
    }
}
