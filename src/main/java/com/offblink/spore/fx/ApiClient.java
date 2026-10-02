package com.offblink.spore.fx;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.json.JSONObject;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

/**
 * JavaFX 侧 REST 客户端。UI 只走 HTTP——不注入 service 不直连 DB（handoff §1 单进程纪律）。
 * 所有响应按统一 R 结构解包：code!=0 抛 ApiException。
 */
public class ApiClient {

    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
    private static final String BASE = "http://127.0.0.1:8080/api";

    private final OkHttpClient http = new OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build();

    private volatile String token;

    /** 业务层异常：code + 服务端 message */
    public static class ApiException extends Exception {
        public final int code;

        ApiException(int code, String message) {
            super(message);
            this.code = code;
        }
    }

    public void setToken(String token) {
        this.token = token;
    }

    public String getToken() {
        return token;
    }

    // ---------- 认证 ----------
    public String login(String username, String password) throws Exception {
        // R<LoginVO> 包装：token 在 data 里，不能在顶层找
        JSONObject data = post("/auth/login", new JSONObject()
                .put("username", username).put("password", password))
                .getJSONObject("data");
        token = data.getString("token");
        return token;
    }

    public void register(String username, String password) throws Exception {
        post("/auth/register", new JSONObject()
                .put("username", username).put("password", password));
    }

    public void logout() {
        try {
            post("/auth/logout", null);
        } catch (Exception ignored) {
            // 本地清 token 即可
        }
        token = null;
    }

    public JSONObject me() throws Exception {
        return get("/users/me");
    }

    public String lanToken() throws Exception {
        return get("/auth/lan-token").getString("data");
    }

    // ---------- 科目 ----------
    public JSONObject categoryTree() throws Exception {
        return get("/categories");
    }

    public void createCategory(String name, String parentId) throws Exception {
        JSONObject body = new JSONObject().put("name", name);
        if (parentId != null) {
            body.put("parentId", parentId);
        }
        post("/categories", body);
    }

    public void renameCategory(String id, String name) throws Exception {
        put("/categories/" + id, new JSONObject().put("name", name));
    }

    public void changeCategoryStatus(String id, int status) throws Exception {
        put("/categories/" + id + "/status?status=" + status, null);
    }

    public void deleteCategory(String id) throws Exception {
        delete("/categories/" + id);
    }

    // ---------- 搜题记录 ----------
    public JSONObject articles(String keyword, String categoryId) throws Exception {
        StringBuilder path = new StringBuilder("/articles?page=1&size=100");
        if (keyword != null && !keyword.isEmpty()) {
            path.append("&keyword=").append(urlEncode(keyword));
        }
        if (categoryId != null && !categoryId.isEmpty()) {
            path.append("&categoryId=").append(urlEncode(categoryId));
        }
        return get(path.toString());
    }

    public void moveArticle(String articleId, String categoryId) throws Exception {
        put("/articles/" + articleId, new JSONObject().put("categoryId", categoryId));
    }

    public void deleteArticle(String articleId) throws Exception {
        delete("/articles/" + articleId);
    }

    // ---------- 本机静默登录（B 方案） ----------
    /** 启动时用本机 device.token 换 JWT；失败返回 false（调用方回登录页） */
    public boolean deviceLogin(String deviceToken) {
        try {
            JSONObject r = request("POST", "/auth/device-login",
                    new JSONObject().put("deviceToken", deviceToken));
            token = r.getString("data");
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 登录成功后调用：轮换并取回本机设备令牌（每次都换新值，旧文件即刻失效） */
    public String createDeviceToken() throws Exception {
        return post("/auth/device-token", null).getString("data");
    }

    // ---------- 题库目录（设置页） ----------
    public JSONObject storageInfo() throws Exception {
        return get("/storage");
    }

    public JSONObject switchStorage(String path) throws Exception {
        return put("/storage", new JSONObject().put("path", path));
    }

    // ---------- HTTP 底座 ----------
    private JSONObject get(String path) throws Exception {
        return request("GET", path, null);
    }

    private JSONObject post(String path, JSONObject body) throws Exception {
        return request("POST", path, body);
    }

    private JSONObject put(String path, JSONObject body) throws Exception {
        return request("PUT", path, body);
    }

    private JSONObject delete(String path) throws Exception {
        return request("DELETE", path, null);
    }

    private JSONObject request(String method, String path, JSONObject body) throws Exception {
        Request.Builder builder = new Request.Builder().url(BASE + path);
        if (token != null) {
            builder.header("Authorization", "Bearer " + token);
        }
        // OkHttp:GET/DELETE 禁止带 body,POST/PUT 必须有 body
        RequestBody rb;
        if (body != null) {
            rb = RequestBody.create(body.toString(), JSON);
        } else if ("POST".equals(method) || "PUT".equals(method) || "PATCH".equals(method)) {
            rb = RequestBody.create("", JSON);
        } else {
            rb = null;
        }
        builder.method(method, rb);
        Response resp = http.newCall(builder.build()).execute();
        String text = (resp.body() != null) ? resp.body().string() : "{}";
        JSONObject jo = new JSONObject(text);
        int code = jo.optInt("code", -1);
        if (code != 0) {
            throw new ApiException(code, jo.optString("message", "未知错误"));
        }
        return jo;
    }

    private String urlEncode(String s) {
        try {
            return java.net.URLEncoder.encode(s, "UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            return s;
        }
    }
}
