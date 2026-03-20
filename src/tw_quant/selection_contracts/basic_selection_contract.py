class BasicSelectionContract:
    """
    選股策略基礎合約類型，所有選股策略需繼承。
    """
    def get_candidates(self, stock_list, as_of_date):
        raise NotImplementedError("子類需實作 get_candidates 或 select 方法")
