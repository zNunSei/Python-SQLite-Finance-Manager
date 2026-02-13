import customtkinter as ctk
import sqlite3
from datetime import datetime
from tkinter import messagebox
import os, re, tempfile, threading

# --- CONFIGURAÇÃO DE GRÁFICOS ---
try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    plt.rcParams.update({
        "figure.facecolor": "#1a1a1a", "axes.facecolor": "#1a1a1a",
        "text.color": "white", "axes.labelcolor": "white",
        "xtick.color": "white", "ytick.color": "white",
        "axes.edgecolor": "#1a1a1a"
    })
    HAS_MATPLOTLIB = True
except: HAS_MATPLOTLIB = False

try: import pandas as pd
except: pd = None

try: from ofxtools.Parser import OFXTree
except: OFXTree = None

import sys

def resource_path(relative_path):
    """ Retorna o caminho correto para o arquivo, seja no Python ou no .exe """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# No seu __init__, mude a linha do db_path para:
# self.db_path = resource_path("gestao_financeira_v1.db")
class FinanceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.diretorio_atual = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(os.getcwd(), "gestao_financeira_v1.db")
        
        # Conexão única e persistente para velocidade
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        self.selecionados = {}
        self.limit_atual = 100 
        self.data_inicio_custom = self.data_fim_custom = None
        
        self.init_db()
        self.load_configs()
        
        ctk.set_appearance_mode(self.tema_atual)
        self.title(self.titulo_sistema)
        self.geometry("1400x900")
        
        self.setup_ui()
        self.update_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        self.conn.close()
        self.destroy()

    def init_db(self):
        self.cursor.executescript("""
            CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT, valor REAL, categoria TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS categorias (nome TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS sistema (chave TEXT PRIMARY KEY, valor TEXT);
            INSERT OR IGNORE INTO sistema VALUES ('titulo_sistema', 'GESTÃO FINANCEIRA PRO');
            INSERT OR IGNORE INTO sistema VALUES ('titulo_cadastro', 'REGISTROS');
            INSERT OR IGNORE INTO sistema VALUES ('tema', 'dark');
        """)
        if self.cursor.execute("SELECT COUNT(*) FROM categorias").fetchone()[0] == 0:
            for c in ["Geral", "Vendas", "Operacional", "Alimentação"]:
                self.cursor.execute("INSERT INTO categorias VALUES (?)", (c,))
        self.conn.commit()

    def load_configs(self):
        self.categorias = [row[0] for row in self.cursor.execute("SELECT nome FROM categorias ORDER BY nome").fetchall()]
        configs = dict(self.cursor.execute("SELECT chave, valor FROM sistema").fetchall())
        self.titulo_sistema = configs.get('titulo_sistema', 'GESTÃO FINANCEIRA PRO')
        self.titulo_cadastro_texto = configs.get('titulo_cadastro', 'REGISTROS')
        self.tema_atual = configs.get('tema', 'dark')

    def setup_ui(self):
        for widget in self.winfo_children(): widget.destroy()
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        
        # SIDEBAR
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=("#d1d1d1", "#151515"))
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        ctk.CTkButton(self.sidebar, text="⚙️ Configurações", fg_color="transparent", text_color=("#333", "#ccc"), command=self.open_settings).pack(pady=(20, 10))
        self.lbl_side = ctk.CTkLabel(self.sidebar, text=self.titulo_cadastro_texto, font=("Arial", 22, "bold"), text_color=("#111", "#fff")); self.lbl_side.pack(pady=30)
        
        for btn in [("➕ Novo Registro", "#2ecc71", self.open_manual_register), ("📊 Estatísticas", "#9b59b6", self.open_charts)]:
            ctk.CTkButton(self.sidebar, text=btn[0], fg_color=btn[1], text_color="#fff", height=45, command=btn[2]).pack(padx=20, pady=10, fill="x")
        
        ctk.CTkLabel(self.sidebar, text="DADOS", font=("Arial", 11, "bold"), text_color="gray").pack(pady=(40, 5))
        self.btn_import = ctk.CTkButton(self.sidebar, text="📥 Importar OFX", fg_color="transparent", border_width=1, text_color=("#111", "#fff"), command=self.start_import_thread)
        self.btn_import.pack(padx=20, pady=5, fill="x")
        ctk.CTkButton(self.sidebar, text="📤 Exportar Excel", fg_color="transparent", border_width=1, text_color=("#111", "#fff"), command=self.export_to_excel).pack(padx=20, pady=5, fill="x")

        # MAIN AREA
        self.main = ctk.CTkFrame(self, fg_color="transparent"); self.main.grid(row=0, column=1, sticky="nsew", padx=25, pady=25)
        self.hp_bar = ctk.CTkProgressBar(self.main, height=12); self.hp_bar.pack(fill="x", pady=(0, 10))
        
        sum_c = ctk.CTkFrame(self.main, fg_color="transparent"); sum_c.pack(fill="x")
        self.lbl_saldo = self.create_val_card(sum_c, "SALDO", "#111", "#252525")
        self.lbl_rec_total = self.create_val_card(sum_c, "RECEITA", "#2ecc71", "#1b3d2f")
        self.lbl_des_total = self.create_val_card(sum_c, "DESPESA", "#e74c3c", "#4d1a1a")

        # FILTROS
        s_bar = ctk.CTkFrame(self.main, fg_color="transparent"); s_bar.pack(fill="x", pady=20)
        self.e_busca = ctk.CTkEntry(s_bar, placeholder_text="🔍 Buscar...", width=250); self.e_busca.pack(side="left", padx=5); self.e_busca.bind("<KeyRelease>", lambda e: self.update_ui())
        self.cb_data = ctk.CTkComboBox(s_bar, values=["Tudo", "Este Mês", "Mês Passado", "Personalizado"], command=lambda _: self.update_ui()); self.cb_data.set("Tudo"); self.cb_data.pack(side="left", padx=5)
        ctk.CTkButton(s_bar, text="📅 Período", width=100, fg_color="transparent", border_width=1, text_color=("#111", "#fff"), command=self.open_custom_date_popup).pack(side="left", padx=5)
        self.cb_ord = ctk.CTkComboBox(s_bar, values=["Data (Novos)", "Data (Antigos)", "Valor (Maior)", "Valor (Menor)"], command=lambda _: self.update_ui()); self.cb_ord.set("Data (Novos)"); self.cb_ord.pack(side="left", padx=5)

        act = ctk.CTkFrame(self.main, fg_color="transparent"); act.pack(fill="x", pady=5)
        self.cb_f = ctk.CTkComboBox(act, values=["Todas"] + self.categorias, command=lambda _: self.update_ui()); self.cb_f.set("Todas"); self.cb_f.pack(side="left", padx=5)
        self.v_all = ctk.BooleanVar(); ctk.CTkCheckBox(act, text="Tudo", variable=self.v_all, text_color=("#111", "#fff"), command=self.toggle_all).pack(side="left", padx=10)
        ctk.CTkButton(act, text="🗑️ Apagar", fg_color="#c0392b", text_color="#fff", width=80, command=self.delete_selected).pack(side="right", padx=5)
        self.cb_m = ctk.CTkComboBox(act, values=self.categorias, width=150); self.cb_m.pack(side="right", padx=5); self.cb_m.set("Mudar Categoria")
        ctk.CTkButton(act, text="Aplicar", width=80, command=self.update_category_mass).pack(side="right", padx=5)
        
        self.lista = ctk.CTkScrollableFrame(self.main, label_text="Movimentações", label_text_color=("#111", "#fff")); self.lista.pack(expand=True, fill="both")

    def create_val_card(self, master, label, t_color, bg_color):
        f = ctk.CTkFrame(master, height=120, corner_radius=20, border_width=2, border_color=("#bbb", "#333"), fg_color=bg_color)
        f.pack(side="left", fill="both", expand=True, padx=5)
        ctk.CTkLabel(f, text=label, font=("Arial", 11, "bold"), text_color="gray").pack(pady=(15, 0))
        lbl = ctk.CTkLabel(f, text="R$ 0,00", font=("Arial", 28, "bold"), text_color=t_color); lbl.pack(pady=(5, 20))
        return lbl

    def update_ui(self, reset=True):
        if reset: self.limit_atual = 100
        for w in self.lista.winfo_children(): w.destroy()
        self.selecionados = {}
        
        busca, periodo, cat_f, ord_v = self.e_busca.get().lower(), self.cb_data.get(), self.cb_f.get(), self.cb_ord.get()
        query = "SELECT * FROM transacoes WHERE 1=1"
        params = []
        
        if busca: query += " AND LOWER(descricao) LIKE ?"; params.append(f"%{busca}%")
        if cat_f != "Todas": query += " AND categoria = ?"; params.append(cat_f)
        if periodo == "Este Mês": query += " AND data LIKE ?"; params.append(f"%/{datetime.now().strftime('%m/%Y')}")
        elif periodo == "Personalizado" and self.data_inicio_custom:
            query += " AND (substr(data,7,4)||substr(data,4,2)||substr(data,1,2)) BETWEEN ? AND ?"
            try: params.extend([self.data_inicio_custom[6:10]+self.data_inicio_custom[3:5]+self.data_inicio_custom[0:2], self.data_fim_custom[6:10]+self.data_fim_custom[3:5]+self.data_fim_custom[0:2]])
            except: pass
        
        ord_map = {"Data (Novos)": "DESC", "Data (Antigos)": "ASC", "Valor (Maior)": "valor DESC", "Valor (Menor)": "valor ASC"}
        query += f" ORDER BY {ord_map.get(ord_v, 'id DESC') if 'Valor' in ord_v else 'substr(data,7,4) '+ord_map.get(ord_v)+' , substr(data,4,2) '+ord_map.get(ord_v)+' , substr(data,1,2) '+ord_map.get(ord_v)}"
        
        rows = self.cursor.execute(query, params).fetchall()
        r_total = sum(r[3] for r in rows if r[1] == 'Receita')
        d_total = sum(r[3] for r in rows if r[1] == 'Despesa')
        
        for r in rows[:self.limit_atual]:
            id_t, tipo, desc, valor, cat_r, data = r
            f = ctk.CTkFrame(self.lista, height=45, corner_radius=10, border_width=1, border_color=("#ddd", "#333")); f.pack(fill="x", pady=3, padx=5)
            var = ctk.BooleanVar(); self.selecionados[id_t] = var
            ctk.CTkCheckBox(f, text="", variable=var, width=20).pack(side="left", padx=10)
            ctk.CTkLabel(f, text=data, width=80, font=("Arial", 10, "bold"), text_color="gray").pack(side="left", padx=10)
            e = ctk.CTkEntry(f, width=400, fg_color="transparent", border_width=0, text_color=("#111", "#fff")); e.insert(0, desc); e.pack(side="left", padx=5)
            e.bind("<FocusOut>", lambda ev, i=id_t, en=e: [self.cursor.execute("UPDATE transacoes SET descricao=? WHERE id=?", (en.get(), i)), self.conn.commit()])
            m = ctk.CTkOptionMenu(f, values=self.categorias, width=130, height=25, command=lambda v, i=id_t: [self.cursor.execute("UPDATE transacoes SET categoria=? WHERE id=?", (v, i)), self.conn.commit(), self.after(50, self.update_ui)]); m.set(cat_r); m.pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"R$ {valor:.2f}", text_color=("#27ae60" if tipo == "Receita" else "#c0392b"), font=("Arial", 13, "bold"), width=110).pack(side="right", padx=10)
        
        self.lbl_saldo.configure(text=f"R$ {r_total-d_total:.2f}", text_color=("#27ae60" if (r_total-d_total) >= 0 else "#c0392b"))
        self.lbl_rec_total.configure(text=f"R$ {r_total:.2f}")
        self.lbl_des_total.configure(text=f"R$ {d_total:.2f}")
        self.hp_bar.set(r_total/(r_total+d_total) if (r_total+d_total)>0 else 0.5)

    def open_settings(self):
        sw = ctk.CTkToplevel(self); sw.title("Configurações"); sw.geometry("500x750"); sw.attributes("-topmost", True); sw.grab_set()
        ctk.CTkLabel(sw, text="TEMA").pack(pady=10)
        ctk.CTkOptionMenu(sw, values=["Dark", "Light", "System"], command=lambda m: [ctk.set_appearance_mode(m), self.cursor.execute("UPDATE sistema SET valor=? WHERE chave='tema'", (m.lower(),)), self.conn.commit()]).pack()
        e_s, e_c = ctk.CTkEntry(sw, width=300), ctk.CTkEntry(sw, width=300)
        e_s.insert(0, self.titulo_sistema); e_c.insert(0, self.titulo_cadastro_texto)
        ctk.CTkLabel(sw, text="NOMES").pack(pady=10); e_s.pack(pady=5); e_c.pack(pady=5)
        ctk.CTkButton(sw, text="Salvar", command=lambda: [self.cursor.execute("UPDATE sistema SET valor=? WHERE chave='titulo_sistema'", (e_s.get().upper(),)), self.cursor.execute("UPDATE sistema SET valor=? WHERE chave='titulo_cadastro'", (e_c.get().upper(),)), self.conn.commit(), self.load_configs(), self.setup_ui()]).pack(pady=10)
        e_n = ctk.CTkEntry(sw, placeholder_text="Nova Categoria..."); e_n.pack(pady=10)
        sl = ctk.CTkScrollableFrame(sw, height=180); sl.pack(fill="both", padx=20)
        def rf():
            self.load_configs(); self.update_ui(False)
            for w in sl.winfo_children(): w.destroy()
            for c in self.categorias:
                f = ctk.CTkFrame(sl, fg_color="transparent"); f.pack(fill="x")
                ctk.CTkLabel(f, text=c).pack(side="left")
                ctk.CTkButton(f, text="🗑️", width=30, fg_color="#c0392b", command=lambda n=c: [self.cursor.execute("DELETE FROM categorias WHERE nome=?", (n,)), self.conn.commit(), self.after(50, rf)]).pack(side="right")
                ctk.CTkButton(f, text="✎", width=30, command=lambda n=c: self.ren_c(n, rf)).pack(side="right", padx=2)
        ctk.CTkButton(sw, text="Adicionar", command=lambda: [self.cursor.execute("INSERT INTO categorias VALUES (?)", (e_n.get(),)), self.conn.commit(), rf()]).pack(); rf()

    def ren_c(self, a, rf):
        v = ctk.CTkInputDialog(text=f"Novo nome para {a}:", title="Editar").get_input()
        if v: [self.cursor.execute("UPDATE categorias SET nome=? WHERE nome=?", (v.strip(), a)), self.cursor.execute("UPDATE transacoes SET categoria=? WHERE categoria=?", (v.strip(), a)), self.conn.commit(), rf()]

    def open_manual_register(self):
        reg = ctk.CTkToplevel(self); reg.title("Novo Registro"); reg.geometry("380x420"); reg.attributes("-topmost", True); reg.grab_set()
        e_d, e_v, e_dt = ctk.CTkEntry(reg, placeholder_text="Descrição"), ctk.CTkEntry(reg, placeholder_text="Valor"), ctk.CTkEntry(reg)
        e_dt.insert(0, datetime.now().strftime("%d/%m/%Y"))
        ctk.CTkLabel(reg, text="Adicionar Transação", font=("Arial", 16, "bold")).pack(pady=15)
        for w in [e_d, e_v, e_dt]: w.configure(width=280); w.pack(pady=5)
        c_t = ctk.CTkComboBox(reg, values=["Receita", "Despesa"], width=280); c_t.set("Despesa"); c_t.pack(pady=10)
        c_c = ctk.CTkComboBox(reg, values=self.categorias, width=280); c_c.set("Geral"); c_c.pack(pady=5)
        def save():
            try:
                self.cursor.execute("INSERT INTO transacoes (tipo,descricao,valor,categoria,data) VALUES (?,?,?,?,?)", (c_t.get(), e_d.get(), float(e_v.get().replace(",", ".")), c_c.get(), e_dt.get()))
                self.conn.commit(); self.update_ui(); reg.destroy()
            except: messagebox.showerror("Erro", "Valor inválido")
        ctk.CTkButton(reg, text="Salvar", fg_color="#2ecc71", command=save).pack(pady=20)

    def open_charts(self):
        if not HAS_MATPLOTLIB: return
        res = dict(self.cursor.execute("SELECT tipo, SUM(valor) FROM transacoes GROUP BY tipo").fetchall())
        gst = self.cursor.execute("SELECT categoria, SUM(valor) FROM transacoes WHERE tipo = 'Despesa' GROUP BY categoria").fetchall()
        if not res: return
        win = ctk.CTkToplevel(self); win.title("Gráficos"); win.geometry("1000x550"); win.attributes("-topmost", True)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5)); fig.patch.set_facecolor('#1a1a1a')
        ax1.set_facecolor('#1a1a1a'); bars = ax1.bar(['Receitas', 'Despesas'], [res.get('Receita', 0), res.get('Despesa', 0)], color=['#2ecc71', '#e74c3c'], width=0.6)
        for b in bars: ax1.text(b.get_x()+b.get_width()/2, b.get_height()+5, f'R${b.get_height():,.0f}', ha='center', color='white', fontweight='bold')
        for s in ax1.spines.values(): s.set_visible(False)
        if gst: ax2.pie([x[1] for x in gst], labels=[x[0] for x in gst], autopct='%1.1f%%', textprops={'color':"w"})
        FigureCanvasTkAgg(fig, master=win).get_tk_widget().pack(fill="both", expand=True, padx=20, pady=20)

    def open_custom_date_popup(self):
        pop = ctk.CTkToplevel(self); pop.title("Datas"); pop.geometry("300x250"); pop.attributes("-topmost", True); pop.grab_set()
        e_i, e_f = ctk.CTkEntry(pop), ctk.CTkEntry(pop)
        ctk.CTkLabel(pop, text="Início:").pack(); e_i.pack(); ctk.CTkLabel(pop, text="Fim:").pack(); e_f.pack()
        def apl(): self.data_inicio_custom, self.data_fim_custom = e_i.get(), e_f.get(); self.cb_data.set("Personalizado"); pop.destroy(); self.update_ui()
        ctk.CTkButton(pop, text="Filtrar", command=apl).pack(pady=20)

    def start_import_thread(self):
        f = ctk.filedialog.askopenfilename(filetypes=[("OFX", "*.ofx")])
        if f: threading.Thread(target=self.import_logic, args=(f,), daemon=True).start()

    def import_logic(self, f_path):
        try:
            with open(f_path, 'rb') as f: raw = f.read()
            content = raw.decode('utf-8', errors='replace').replace('\u0192', '')
            content = re.sub(r'<(ORG|FID)>.*?</\1>', r'<\1>BANCO</\1>', content, flags=re.IGNORECASE)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ofx", mode='w', encoding='utf-8') as t: t.write(content); t_path = t.name
            parser = OFXTree(); parser.parse(t_path); ofx = parser.convert(); stmt = ofx.statements[0]
            novos = []
            for tx in stmt.banktranlist:
                tipo, val, desc, dt = ("Receita" if tx.trnamt > 0 else "Despesa"), abs(float(tx.trnamt)), str(tx.memo).encode('latin-1', 'ignore').decode('utf-8', 'ignore'), tx.dtposted.strftime("%d/%m/%Y")
                if not self.cursor.execute("SELECT 1 FROM transacoes WHERE descricao=? AND data=? AND valor=? LIMIT 1", (desc, dt, val)).fetchone(): novos.append((tipo, desc, val, "Geral", dt))
            if novos: self.cursor.executemany("INSERT INTO transacoes (tipo,descricao,valor,categoria,data) VALUES (?,?,?,?,?)", novos); self.conn.commit()
            os.unlink(t_path); self.after(0, lambda: [self.update_ui(), messagebox.showinfo("OK", f"Importados {len(novos)} itens.")])
        except Exception as e: self.after(0, lambda: messagebox.showerror("Erro", str(e)))

    def export_to_excel(self):
        if not pd: return
        df = pd.read_sql_query("SELECT * FROM transacoes", self.conn)
        df.to_excel(os.path.join(self.diretorio_atual, "Financeiro.xlsx"), index=False); os.startfile(self.diretorio_atual)
    
    def toggle_all(self): [v.set(self.v_all.get()) for v in self.selecionados.values()]
    def delete_selected(self):
        ids = [i for i, v in self.selecionados.items() if v.get()]
        if ids and messagebox.askyesno("Apagar", f"Apagar {len(ids)} registros?"):
            for i in ids: self.cursor.execute("DELETE FROM transacoes WHERE id=?", (i,))
            self.conn.commit(); self.update_ui()
    def update_category_mass(self):
        nc, ids = self.cb_m.get(), [i for i, v in self.selecionados.items() if v.get()]
        if ids: 
            for i in ids: self.cursor.execute("UPDATE transacoes SET categoria=? WHERE id=?", (nc, i))
            self.conn.commit(); self.update_ui()

if __name__ == "__main__":
    FinanceApp().mainloop()