from esim.models import Market

def digiseller_market_ids(request):
    global_plati_id = Market.objects.filter(market_id=1).values_list('market_id', flat=True).first()
    global_ggesel_id = Market.objects.filter(market_id=1271).values_list('market_id', flat=True).first()
    
    return {
        'global_plati_id': global_plati_id,
        'global_ggesel_id': global_ggesel_id,
    }
