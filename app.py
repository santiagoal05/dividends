from flask import Flask, render_template, request
from datetime import datetime, date, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
pio.templates.default = "plotly_dark"

app = Flask(__name__)

def calculate_dividend_channels(ticker):
    try:
        today = date.today()
        start_date = today - timedelta(days=365 * 12)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = today.strftime('%Y-%m-%d')
        
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start_date_str, end=end_date_str)
        
        if hist.empty:
            return None, "No se encontraron datos históricos"
        
        if hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)
        
        if "Dividends" not in hist.columns:
            hist["Dividends"] = 0.0
        
        last_date = hist.index[-1].date()
        if (today - last_date) > timedelta(days=7):
            return None, "Datos históricos desactualizados (>7 días)"
        
        hist['Dividends_Yearly'] = hist['Dividends'].rolling(window=250, min_periods=1).sum().fillna(0)
        hist['Dividend_Yield'] = (hist['Dividends_Yearly'] / hist['Close']).fillna(0) * 100
        
        if hist['Dividend_Yield'].dropna().empty:
            return None, "No hay datos de dividendos disponibles"
        
        avg_high = hist['Dividend_Yield'].quantile(0.9)
        avg_low = hist['Dividend_Yield'].quantile(0.1)
        current_yield = hist['Dividend_Yield'].iloc[-1]
        
        if pd.isna(current_yield):
            status = "Sin rendimiento actual"
        elif current_yield > avg_high:
            status = "Potencialmente infravalorado"
        elif current_yield < avg_low:
            status = "Potencialmente sobrevalorado"
        else:
            status = "Rango neutro"
        
        fig = px.line(
            hist, 
            x=hist.index, 
            y='Dividend_Yield',
            title=f"Análisis de Canales de Dividendos - {ticker} (Últimos 12 años)",
            labels={'Dividend_Yield': 'Rendimiento Anual (%)'}
        )
        fig.add_hline(
            y=avg_high, 
            line_dash="dash", 
            line_color="#2c3e50",
            annotation_text=f"Top 10%: {avg_high:.1f}%", 
            annotation_position="bottom right"
        )
        fig.add_hline(
            y=avg_low, 
            line_dash="dash", 
            line_color="#c0392b",
            annotation_text=f"Low 10%: {avg_low:.1f}%", 
            annotation_position="top right"
        )
        fig.add_vrect(
            x0=hist.index.min(), 
            x1=hist.index.max(), 
            y0=avg_high, 
            y1=100,
            fillcolor="#2c3e50", 
            opacity=0.1, 
            layer="below"
        )
        fig.add_vrect(
            x0=hist.index.min(), 
            x1=hist.index.max(), 
            y0=0, 
            y1=avg_low,
            fillcolor="#c0392b", 
            opacity=0.1, 
            layer="below"
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='#ecf0f1',
            height=600,
            font=dict(family='Roboto', size=11, color='#34495e'),
            title_font_size=16,
            yaxis=dict(tickformat=".1f", title_font_size=12),
            xaxis=dict(rangeslider_visible=False)
        )
        return fig, status
    except Exception as e:
        return None, f"Error procesando {ticker}: {str(e)}"

def calculate_fair_value_bands(hist, divs):
    try:
        current_year = datetime.now().year
        start_year = current_year - 12
        full_years = range(start_year, current_year)
        
        annual_data = []
        for year in full_years:
            year_mask = (hist.index.year == year)
            if year_mask.any():
                max_price = hist.loc[year_mask, 'High'].max()
                min_price = hist.loc[year_mask, 'Low'].min()
                year_div = divs[divs.index.year == year].sum()
                
                if year_div > 0 and max_price > 0 and min_price > 0:
                    annual_data.append({
                        'Year': year,
                        'Dividend': year_div,
                        'Yield_Max': year_div / min_price,
                        'Yield_Min': year_div / max_price
                    })
        
        if len(annual_data) < 3:
            return None, None, None, None, "Insufficient data for fair value comparison"
        
        df = pd.DataFrame(annual_data)
        max_yield = df['Yield_Max'].max()
        min_yield = df['Yield_Min'].min()
        
        df['Banda_Sobre'] = df['Dividend'] / min_yield
        df['Banda_Infra'] = df['Dividend'] / max_yield
        
        return df, max_yield, min_yield, None, None
    except Exception as e:
        return None, None, None, None, f"Error calculating bands: {str(e)}"

@app.route('/', methods=['GET', 'POST'])
def home():
    error = None
    status = "No analysis performed"
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').upper().strip()
        if not ticker:
            error = "Please enter a valid ticker symbol"
            return render_template('index.html', error=error)
        
        # Genera el gráfico de Canales de Dividendos (Gráfico 1)
        fig1, status_div = calculate_dividend_channels(ticker)
        if fig1 is None:
            status = status_div
            return render_template('index.html', error=status)
        
        # Obtiene datos para el Análisis de Valoración (Gráfico 2)
        stock = yf.Ticker(ticker)
        today = date.today()
        start_date = today - timedelta(days=365 * 12)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = today.strftime('%Y-%m-%d')
        hist = stock.history(start=start_date_str, end=end_date_str)
        hist.index = hist.index.tz_localize(None)
        divs = stock.dividends.copy()
        divs.index = divs.index.tz_localize(None)
        divs = divs[(divs.index >= hist.index.min()) & (divs.index <= hist.index.max())]
        
        yearly_data, max_yield, min_yield, _, error_bands = calculate_fair_value_bands(hist, divs)
        
        if yearly_data is not None:
            # Genera el gráfico de Análisis de Valoración (Gráfico 2)
            yearly_bands = yearly_data[['Year', 'Banda_Sobre', 'Banda_Infra']].copy()
            yearly_bands['Year_End'] = yearly_bands['Year'].apply(lambda y: pd.Timestamp(year=y, month=12, day=31))
            yearly_bands.set_index('Year_End', inplace=True)
            
            fig2 = go.Figure()
            
            # Línea del precio de cierre
            fig2.add_trace(go.Scatter(
                x=hist.index,
                y=hist['Close'],
                name='Closing Price',
                line=dict(color='#2A5CAA', width=2.5),
                hovertemplate='Price: $%{y:.2f}<extra></extra>'
            ))
            
            # Líneas de bandas anuales
            fig2.add_trace(go.Scatter(
                x=yearly_bands.index,
                y=yearly_bands['Banda_Sobre'],
                name='Overvalued',
                mode='lines+markers',
                line=dict(color='firebrick', dash='dot', width=2),
                marker=dict(size=8, color='firebrick'),
                hovertemplate='Year: %{x|%Y}<br>Band: $%{y:.2f}<extra></extra>'
            ))
            
            fig2.add_trace(go.Scatter(
                x=yearly_bands.index,
                y=yearly_bands['Banda_Infra'],
                name='Undervalued',
                mode='lines+markers',
                line=dict(color='green', dash='dot', width=2),
                marker=dict(size=8, color='green'),
                hovertemplate='Year: %{x|%Y}<br>Band: $%{y:.2f}<extra></extra>'
            ))
            
            # Rellenar el área entre las bandas
            fig2.add_trace(go.Scatter(
                x=yearly_bands.index.tolist() + yearly_bands.index[::-1].tolist(),
                y=yearly_bands['Banda_Sobre'].tolist() + yearly_bands['Banda_Infra'][::-1].tolist(),
                fill='toself',
                fillcolor='rgba(189,195,199,0.2)',
                line=dict(color='rgba(255,255,255,0)'),
                name='Value Range',
                hoverinfo='skip'
            ))
            
            # Línea del precio actual
            current_price = hist['Close'].iloc[-1]
            fig2.add_hline(
                y=current_price,
                line_color='#FF7043',
                line_dash='dash',
                line_width=2,
                annotation_text=f'Current Price: ${current_price:.2f}',
                annotation_position='bottom right',
                annotation=dict(font_color='#455A64')
            )
            
            # Métricas clave
            max_hist_price = hist['High'].max()
            min_hist_price = hist['Low'].min()
            info_text = (
                f"Máximo Histórico: ${max_hist_price:.2f}\n"
                f"Mínimo Histórico: ${min_hist_price:.2f}\n"
                f"Precio Actual: ${current_price:.2f}"
            )
            
            fig2.update_layout(
                title=f"Weiss Analysis for {ticker.upper()}",
                xaxis=dict(
                    title='Fecha',
                    type='date',
                    dtick='M12',
                    tickformat='%Y',
                    rangeslider_visible=False
                ),
                yaxis=dict(
                    title='Precio (USD)',
                    tickformat='$,.2f',
                    gridcolor='#dddddd'
                ),
                hovermode='x unified',
                template='plotly_white',
                height=600,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0.01
                ),
                margin=dict(l=50, r=50, t=80, b=50)
            )
            
            # Anotación de información clave
            fig2.add_annotation(
                text=info_text,
                xref='paper',
                yref='paper',
                x=0.03,
                y=0.95,
                align='left',
                showarrow=False,
                bordercolor='#CCCCCC',
                borderwidth=1,
                borderpad=4,
                bgcolor='white',
                opacity=0.8,
                font=dict(color="#455A64", size=12)
            )
            
            return render_template('result.html',
                                   plot1=fig1.to_html(full_html=False),
                                   plot2=fig2.to_html(full_html=False),
                                   status=status_div, ticker=ticker)
        else:
            error = error_bands
    return render_template('index.html', error=error)

if __name__ == '__main__':
    app.run(debug=True)
