import pandas as pd
from sklearn.model_selection import train_test_split

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import BertTokenizer, BertModel
from torch import cuda
import time


# Datasetの定義
class CreateDataset(Dataset):
    def __init__(self, X, y, tokenizer, max_len):
        self.X = X
        self.y = y
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):  # len(Dataset)で返す値を指定
        return len(self.y)

    def __getitem__(self, index):  # Dataset[index]で返す値を指定
        text = self.X[index]
        inputs = self.tokenizer.encode_plus(
            text,
            add_special_tokens=True,
            max_length=self.max_len,
            pad_to_max_length=True
        )
        ids = inputs['input_ids']
        mask = inputs['attention_mask']

        return {
            'ids': torch.LongTensor(ids),
            'mask': torch.LongTensor(mask),
            'labels': torch.Tensor(self.y[index])
        }


# BERT分類モデルの定義
class BERTClass(torch.nn.Module):
    def __init__(self, drop_rate, otuput_size):
        super().__init__()
        self.bert = BertModel.from_pretrained('bert-base-uncased')
        self.drop = torch.nn.Dropout(drop_rate)
        self.fc = torch.nn.Linear(768, otuput_size)

    def forward(self, ids, mask):
        out = self.bert(ids, attention_mask=mask)
        out = self.fc(self.drop(out[1]))
        return out


def calculate_loss_and_accuracy(model, criterion, loader, device):
    """ 損失・正解率を計算"""
    model.eval()
    loss = 0.0
    total = 0
    correct = 0
    with torch.no_grad():
        for data in loader:
            # デバイスの指定
            ids = data['ids'].to(device)
            mask = data['mask'].to(device)
            labels = data['labels'].to(device)

            # 順伝播
            outputs = model.forward(ids, mask)

            # 損失計算
            loss += criterion(outputs, labels).item()

            # 正解率計算
            pred = torch.argmax(outputs, dim=-1).cpu().numpy()  # バッチサイズの長さの予測ラベル配列
            labels = torch.argmax(labels, dim=-1).cpu().numpy()  # バッチサイズの長さの正解ラベル配列
            total += len(labels)
            correct += (pred == labels).sum().item()

    return loss / len(loader), correct / total


def train_model(dataset_train, dataset_valid, batch_size, model, criterion, optimizer, num_epochs, device=None):
    """モデルの学習を実行し、損失・正解率のログを返す"""
    # デバイスの指定
    model.to(device)

    # dataloaderの作成
    dataloader_train = DataLoader(dataset_train, batch_size=batch_size, shuffle=True)
    dataloader_valid = DataLoader(dataset_valid, batch_size=len(dataset_valid), shuffle=False)

    # 学習
    log_train = []
    log_valid = []
    for epoch in range(num_epochs):
        # 開始時刻の記録
        s_time = time.time()

        # 訓練モードに設定
        model.train()
        for data in dataloader_train:
            # デバイスの指定
            ids = data['ids'].to(device)
            mask = data['mask'].to(device)
            labels = data['labels'].to(device)

            # 勾配をゼロで初期化
            optimizer.zero_grad()

            # 順伝播 + 誤差逆伝播 + 重み更新
            outputs = model.forward(ids, mask)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

        # 損失と正解率の算出
        loss_train, acc_train = calculate_loss_and_accuracy(model, criterion, dataloader_train, device)
        loss_valid, acc_valid = calculate_loss_and_accuracy(model, criterion, dataloader_valid, device)
        log_train.append([loss_train, acc_train])
        log_valid.append([loss_valid, acc_valid])

        # チェックポイントの保存
        torch.save(
            {'epoch': epoch, 'model_state_dict': model.state_dict(), 'optimizer_state_dict': optimizer.state_dict()},
            f'checkpoint{epoch + 1}.pt')

        # 終了時刻の記録
        e_time = time.time()

        # ログを出力
        print(
            f'epoch: {epoch + 1}, loss_train: {loss_train:.4f}, accuracy_train: {acc_train:.4f}, loss_valid: {loss_valid:.4f}, accuracy_valid: {acc_valid:.4f}, {(e_time - s_time):.4f}sec')

    return {'train': log_train, 'valid': log_valid}


# 正解率の算出
def calculate_accuracy(model, dataset, device):
    # Dataloaderの作成
    loader = DataLoader(dataset, batch_size=len(dataset), shuffle=False)

    model.eval()
    total = 0
    correct = 0
    with torch.no_grad():
        for data in loader:
            # デバイスの指定
            ids = data['ids'].to(device)
            mask = data['mask'].to(device)
            labels = data['labels'].to(device)

            # 順伝播 + 予測値の取得 + 正解数のカウント
            print(type(ids), type(mask))
            outputs = model.forward(ids, mask)
            pred = torch.argmax(outputs, dim=-1).cpu().numpy()
            labels = torch.argmax(labels, dim=-1).cpu().numpy()
            total += len(labels)
            correct += (pred == labels).sum().item()

    return correct / total


if __name__ == '__main__':
    start = time.time()
    # データの読込
    df = pd.read_csv('./newsCorpora_re.csv', header=None, sep='\t',
                     names=['ID', 'TITLE', 'URL', 'PUBLISHER', 'CATEGORY', 'STORY', 'HOSTNAME', 'TIMESTAMP'])

    # データの抽出
    df = df.loc[
        df['PUBLISHER'].isin(['Reuters', 'Huffington Post', 'Businessweek', 'Contactmusic.com', 'Daily Mail']),
        ['TITLE', 'CATEGORY']]

    # データの分割
    train, valid_test = train_test_split(df, test_size=0.2, shuffle=True, random_state=123, stratify=df['CATEGORY'])
    valid, test = train_test_split(valid_test, test_size=0.5, shuffle=True, random_state=123,
                                   stratify=valid_test['CATEGORY'])
    train.reset_index(drop=True, inplace=True)
    valid.reset_index(drop=True, inplace=True)
    test.reset_index(drop=True, inplace=True)

    # データの中身
    print(train.head())

    # 事例数の確認
    print('【学習データ】')
    print(train['CATEGORY'].value_counts())
    print('【検証データ】')
    print(valid['CATEGORY'].value_counts())
    print('【評価データ】')
    print(test['CATEGORY'].value_counts())

    # 正解ラベルのone-hot化
    y_train = pd.get_dummies(train, columns=['CATEGORY'])[['CATEGORY_b', 'CATEGORY_e', 'CATEGORY_t', 'CATEGORY_m']].values
    y_valid = pd.get_dummies(valid, columns=['CATEGORY'])[['CATEGORY_b', 'CATEGORY_e', 'CATEGORY_t', 'CATEGORY_m']].values
    y_test = pd.get_dummies(test, columns=['CATEGORY'])[['CATEGORY_b', 'CATEGORY_e', 'CATEGORY_t', 'CATEGORY_m']].values

    # Datasetの作成
    max_len = 20
    tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
    dataset_train = CreateDataset(train['TITLE'][:1000], y_train[:1000], tokenizer, max_len)
    dataset_valid = CreateDataset(valid['TITLE'][:300], y_valid[:300], tokenizer, max_len)
    dataset_test = CreateDataset(test['TITLE'][:300], y_test[:300], tokenizer, max_len)

    for var in dataset_train[0]:
        print(f'{var}: {dataset_train[0][var]}')

    # パラメータの設定
    DROP_RATE = 0.4
    OUTPUT_SIZE = 4
    BATCH_SIZE = 4
    NUM_EPOCHS = 4
    LEARNING_RATE = 2e-5

    # モデルの定義
    model = BERTClass(DROP_RATE, OUTPUT_SIZE)
    # 損失関数の定義
    criterion = torch.nn.BCEWithLogitsLoss()
    # オプティマイザの定義
    optimizer = torch.optim.AdamW(params=model.parameters(), lr=LEARNING_RATE)
    # デバイスの指定
    device = 'cuda' if cuda.is_available() else 'cpu'
    # モデルの学習
    log = train_model(dataset_train, dataset_valid, BATCH_SIZE, model,
                      criterion, optimizer, NUM_EPOCHS, device=device)

    print(f'正解率（学習データ）：{calculate_accuracy(model, dataset_train, device):.3f}')
    print(f'正解率（検証データ）：{calculate_accuracy(model, dataset_valid, device):.3f}')
    print(f'正解率（評価データ）：{calculate_accuracy(model, dataset_test, device):.3f}')

    end = time.time()
    print('time :', end - start)
